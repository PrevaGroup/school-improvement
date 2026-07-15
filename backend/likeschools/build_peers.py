"""Build "Schools Like You" peer groups — the Mahalanobis matching engine.

Implements backend/likeschools/school-classification-spec.md §4-§5.3: for each school,
the k nearest schools of the same instructional level by Mahalanobis distance over
standardized demographic INPUT features (never outcomes — D1). Reads the deployed public
`dim_school`, writes three public marts (feat_match_vector / mart_school_peer /
model_partition_stats). Serving is then a cheap indexed lookup (app/marts.py).

Method per partition (spec §4.2 Path A):
  impute (within-level median) -> z-score -> Ledoit-Wolf shrinkage covariance ->
  NearestNeighbors(metric='mahalanobis', VI=precision_) -> keep k nearest (drop self).

Deviations from the spec, to fit the deployed CA data:
  - keyed on dim_school.school_id (NCES) / school_year (text), not `nces_id`/smallint;
  - features from dim_school: pct_sed, pct_el, pct_swd, enroll_total(log1p), locale(1-hot);
  - race excluded from the match vector (D8 default; dim_school carries no per-school race);
  - one run-year label (--year, default = max dim_school.school_year) covers all current
    schools, avoiding fragmentation from mixed fact-stub years.

Run in Cloud Shell (DB via Auth Proxy + ADC), from backend/ (needs scikit-learn):
    python -m likeschools.build_peers [--k 50] [--year 2025-26] [--conf-pctile 90] [--dry-run]
"""
from __future__ import annotations

import argparse
import math
import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional

# -> backend/, so `app.config` resolves when this runs as a script. parents[1], not [2]:
# this file moved up a level (etl/peers/ -> likeschools/) in the reorg, and [2] now lands on
# the repo root. Tests never catch this — conftest.py already puts backend/ on sys.path.
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
from sklearn.covariance import LedoitWolf
from sklearn.neighbors import NearestNeighbors
from sqlalchemy import create_engine, text

from app.config import settings
from .models import FeatMatchVector, MartSchoolPeer, ModelPartitionStats

FEATURES = [
    "f_econ_disadv", "f_el", "f_swd", "f_enroll_log",
    "f_locale_city", "f_locale_suburb", "f_locale_town", "f_locale_rural",
]
CORE = ("f_econ_disadv", "f_el", "f_swd", "f_enroll_log")  # imputable continuous features
MIN_PARTITION = 3  # below this, can't form a meaningful peer set
BATCH = 1000


def level_bucket(school_level: Optional[str]) -> str:
    s = (school_level or "").strip().lower()
    if not s:
        return "Combined-Other"
    if "combination" in s or "k-12" in s or "k-8" in s or "span" in s:
        return "Combined-Other"
    if "elementary" in s or "primary" in s:
        return "Primary"
    if "middle" in s or "intermediate" in s or "junior" in s:
        return "Middle"
    if "high" in s:
        return "High"
    return "Combined-Other"


def locale_onehot(loc: Optional[str]) -> tuple[float, float, float, float]:
    """(city, suburb, town, rural) from the CDE/NCES locale string or leading digit."""
    s = (loc or "").strip().lower()
    d = s[:1]
    if d == "1" or "city" in s:
        return (1.0, 0.0, 0.0, 0.0)
    if d == "2" or "suburb" in s:
        return (0.0, 1.0, 0.0, 0.0)
    if d == "3" or "town" in s:
        return (0.0, 0.0, 1.0, 0.0)
    if d == "4" or "rural" in s:
        return (0.0, 0.0, 0.0, 1.0)
    return (0.0, 0.0, 0.0, 0.0)


def _f(x):
    return None if x is None else float(x)


def load_schools(conn):
    rows = conn.execute(text(
        "SELECT school_id, school_year, school_level, locale, enroll_total, "
        "pct_sed, pct_el, pct_swd FROM dim_school"
    )).mappings().all()
    out = []
    for r in rows:
        out.append({
            "school_id": r["school_id"],
            "school_year": r["school_year"],
            "level_bucket": level_bucket(r["school_level"]),
            "f_econ_disadv": _f(r["pct_sed"]),
            "f_el": _f(r["pct_el"]),
            "f_swd": _f(r["pct_swd"]),
            "f_enroll_log": (math.log1p(float(r["enroll_total"])) if r["enroll_total"] is not None else None),
            "locale": locale_onehot(r["locale"]),
        })
    return out


def build_partition(rows: list[dict], k: int, conf_pctile: float, run_year: str, bucket: str):
    """Impute -> standardize -> Ledoit-Wolf Mahalanobis kNN. Returns (feat_rows, peer_rows, stats)."""
    n = len(rows)
    # 1) impute continuous features to the within-partition median; flag imputations
    medians = {}
    for c in CORE:
        vals = [r[c] for r in rows if r[c] is not None]
        medians[c] = float(np.median(vals)) if vals else 0.0
    for r in rows:
        imp = 0
        for c in CORE:
            if r[c] is None:
                r[c] = medians[c]
                imp += 1
        r["n_imputed"] = imp
        r["f_locale_city"], r["f_locale_suburb"], r["f_locale_town"], r["f_locale_rural"] = r["locale"]

    X = np.array([[r[c] for c in FEATURES] for r in rows], dtype=float)

    # 2) z-score within partition (guard zero-variance columns, e.g. an absent locale type)
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd_safe = np.where(sd == 0, 1.0, sd)
    Z = (X - mu) / sd_safe

    # 3) Ledoit-Wolf shrinkage covariance -> inverse covariance (precision) = VI
    lw = LedoitWolf().fit(Z)
    VI = lw.precision_

    # 4) Mahalanobis kNN. k_eff bounded by partition size; small partitions are low-confidence.
    k_eff = min(k, n - 1)
    nn = NearestNeighbors(n_neighbors=k_eff + 1, metric="mahalanobis", metric_params={"VI": VI}).fit(Z)
    dist, idx = nn.kneighbors(Z)

    kth_dists = []
    peer_lists = []  # per school: list of (peer_row_index, distance) excluding self
    for i in range(n):
        pairs = [(j, d) for j, d in zip(idx[i], dist[i]) if j != i][:k_eff]
        peer_lists.append(pairs)
        kth_dists.append(pairs[-1][1] if pairs else 0.0)
    thr = float(np.percentile(kth_dists, conf_pctile)) if kth_dists else float("inf")

    feat_rows, peer_rows = [], []
    for i, r in enumerate(rows):
        feat_rows.append({
            "school_id": r["school_id"], "school_year": run_year, "level_bucket": bucket,
            "f_econ_disadv": r["f_econ_disadv"], "f_el": r["f_el"], "f_swd": r["f_swd"],
            "f_enroll_log": r["f_enroll_log"],
            "f_locale_city": r["f_locale_city"], "f_locale_suburb": r["f_locale_suburb"],
            "f_locale_town": r["f_locale_town"], "f_locale_rural": r["f_locale_rural"],
            "n_imputed": r["n_imputed"],
        })
        low = (r["n_imputed"] > 2) or (k_eff < k) or (kth_dists[i] > thr)
        for rank, (j, d) in enumerate(peer_lists[i], start=1):
            peer_rows.append({
                "school_id": r["school_id"], "peer_school_id": rows[j]["school_id"],
                "school_year": run_year, "rank": rank, "distance": float(d),
                "level_bucket": bucket, "low_confidence": bool(low),
            })

    stats = {
        "school_year": run_year, "level_bucket": bucket, "feature_names": FEATURES,
        "means": mu.tolist(), "sds": sd.tolist(), "shrinkage": float(lw.shrinkage_),
        "precision_mat": VI.ravel().tolist(), "k": k_eff,
        "built_at": datetime.now(timezone.utc),
    }
    return feat_rows, peer_rows, stats


def _insert(conn, model, rows: list[dict]):
    tbl = model.__table__
    for i in range(0, len(rows), BATCH):
        conn.execute(tbl.insert(), rows[i:i + BATCH])


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build Schools-Like-You peer groups from dim_school.")
    ap.add_argument("--k", type=int, default=50, help="peers per school (D7 default 50)")
    ap.add_argument("--year", default=None, help="run-year label; default = max dim_school.school_year")
    ap.add_argument("--conf-pctile", type=float, default=90.0, help="kth-distance percentile that trips low_confidence")
    ap.add_argument("--dry-run", action="store_true", help="compute + report; no writes")
    args = ap.parse_args(argv)

    eng = create_engine(settings.migration_database_url)
    with eng.connect() as conn:
        schools = load_schools(conn)
    run_year = args.year or max((s["school_year"] for s in schools if s["school_year"]), default="current")
    print(f"[peers] {len(schools)} schools, run_year={run_year}, k={args.k}", file=sys.stderr)

    parts: dict[str, list[dict]] = {}
    for s in schools:
        parts.setdefault(s["level_bucket"], []).append(s)

    all_feat, all_peer, all_stats = [], [], []
    for bucket, rows in sorted(parts.items()):
        if len(rows) < MIN_PARTITION:
            print(f"[peers] skip {bucket}: only {len(rows)} schools (< {MIN_PARTITION})", file=sys.stderr)
            continue
        f, p, st = build_partition(rows, args.k, args.conf_pctile, run_year, bucket)
        n_low = len({r["school_id"] for r in p if r["low_confidence"]})
        print(f"[peers] {bucket}: {len(rows)} schools -> {len(p)} peer edges "
              f"(k_eff={st['k']}, shrinkage={st['shrinkage']:.3f}, {n_low} low-confidence)", file=sys.stderr)
        all_feat += f
        all_peer += p
        all_stats.append(st)

    if args.dry_run:
        print(f"[peers] --dry-run: would write {len(all_feat)} vectors, {len(all_peer)} peer edges, "
              f"{len(all_stats)} partition-stats rows for {run_year}", file=sys.stderr)
        return 0

    with eng.begin() as conn:
        for model in (MartSchoolPeer, FeatMatchVector, ModelPartitionStats):
            conn.execute(model.__table__.delete().where(model.__table__.c.school_year == run_year))
        _insert(conn, FeatMatchVector, all_feat)
        _insert(conn, MartSchoolPeer, all_peer)
        _insert(conn, ModelPartitionStats, all_stats)
    print(f"[peers] wrote {len(all_peer)} peer edges across {len(all_stats)} partitions for {run_year}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
