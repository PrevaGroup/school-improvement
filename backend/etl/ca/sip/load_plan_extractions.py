"""Load extracted plan JSONs into the public plan_extraction (JSONB) table.

The serving source for the plan-content marts: it keeps the FULL extraction (provenance
quotes, funding text, proposed metric links) that the normalized plan_* tables drop.
Public tier — no tenant, no RLS (SPSAs are public documents).

Run in Cloud Shell (DB via the loaders' engine + ADC), from backend/:
    python -m etl.ca.sip.load_plan_extractions \
      --in-prefix gs://school-improvement-501916-raw/raw/ca/districts/0622500/sip/extracted \
      [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

sys.path.append(str(pathlib.Path(__file__).resolve().parents[3]))  # -> backend/

import fsspec
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .models import PlanExtraction

from ._db import _engine

DEFAULT_WORKERS = 16  # fetches are network-bound (one GCS GET each) — overlap them


def _fetch_row(fs, src: str) -> dict:
    """One GCS GET + parse. Returns the plan_extraction row dict (raises on bad JSON/missing key)."""
    doc = json.loads(fs.cat_file(src))
    return dict(
        plan_id=doc["plan_id"],
        school_id=doc.get("school_id"),
        plan_year=doc.get("plan_year"),
        plan_type=doc.get("plan_type"),
        extracted_at=(doc.get("source") or {}).get("extracted_at"),
        document=doc,
    )


def dedup_by_plan_id(rows: list[dict]) -> list[dict]:
    """Collapse rows sharing a plan_id (last wins), preserving first-seen order.

    `plan_id` is deterministic, so two files that resolve to the same plan — two PDFs for one
    school, or two district-scope LCAPs in a year — carry identical plan_ids under different
    filenames. Postgres rejects an ON CONFLICT DO UPDATE that touches the same row twice
    ("cannot affect row a second time"), which would abort the ENTIRE upsert window, not just
    the duplicate. Same guard `_shared._flush_facts` applies to fact rows.
    """
    deduped: dict[str, dict] = {}
    for r in rows:
        deduped[r["plan_id"]] = r
    return list(deduped.values())


def list_json(prefix: str):
    fs, _ = fsspec.core.url_to_fs(prefix)
    scheme = prefix.split("://", 1)[0] if "://" in prefix else None
    out = []
    for p in fs.glob(prefix.rstrip("/") + "/*.json"):
        src = p if ("://" in p or scheme is None) else f"{scheme}://{p}"
        out.append((p.rsplit("/", 1)[-1], src))
    return fs, sorted(out)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Load extracted plan JSONs into public plan_extraction (JSONB).")
    ap.add_argument("--in-prefix", required=True, help="gs:// prefix (or local dir) of the extracted *.json")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help=f"concurrent GCS fetches (default {DEFAULT_WORKERS}); the loop is network-bound")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    fs, files = list_json(args.in_prefix)
    if args.limit:
        files = files[: args.limit]
    n = len(files)
    print(f"[extractions] {n} JSONs under {args.in_prefix}", file=sys.stderr, flush=True)

    # Fetch+parse concurrently: each file is a serial GCS round-trip otherwise, so N files
    # cost N latencies back-to-back. A thread pool overlaps them (I/O-bound → the GIL is
    # released during the GET). Per-file try/except keeps the batch resilient to one bad file.
    rows, errors = [], []
    done = 0
    workers = max(1, min(args.workers, n or 1))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_row, fs, src): fname for fname, src in files}
        for fut in as_completed(futs):
            fname = futs[fut]
            done += 1
            try:
                rows.append(fut.result())
                print(f"[extractions] ({done}/{n}) ok {fname}", file=sys.stderr, flush=True)
            except Exception as e:
                errors.append((fname, str(e)))
                print(f"[extractions] ({done}/{n}) ERROR {fname}: {e}", file=sys.stderr, flush=True)

    print(f"[extractions] parsed {len(rows)} ok, {len(errors)} errors", file=sys.stderr, flush=True)
    if args.dry_run or not rows:
        for r in rows:
            print(f"  would upsert {r['plan_id']} (school {r['school_id']})", file=sys.stderr)
        return 1 if errors else 0

    deduped = dedup_by_plan_id(rows)
    if len(deduped) < len(rows):
        print(f"[extractions] {len(rows) - len(deduped)} duplicate plan_id(s) collapsed (last wins)",
              file=sys.stderr, flush=True)

    with _engine().begin() as conn:
        stmt = pg_insert(PlanExtraction).values(deduped)
        conn.execute(stmt.on_conflict_do_update(
            index_elements=["plan_id"],
            set_={c: stmt.excluded[c] for c in ("school_id", "plan_year", "plan_type", "extracted_at", "document")},
        ))
    print(f"[extractions] upserted {len(deduped)} plan_extraction rows")
    for f, e in errors:
        print(f"  error {f}: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
