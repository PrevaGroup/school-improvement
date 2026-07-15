"""Shared machinery for the California public-data loaders.

Per-fact scripts (`load_ca_<fact>.py`) are thin: they define a SPEC and call
`run_metric_loader`. `seed_ca_dims.py` calls `run_seed`. All CDE metric files that
share the school x reporting-category x rate shape reuse `load_metric_file`.

Everything loads into the PUBLIC tier (tenant_id='public').
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))  # -> backend/

import fsspec  # local paths AND gs:// URIs (gcsfs, via ADC)
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.models import (
    DimSchool, DimStudentGroup, GroupCrosswalk, DimMetric, DimPeriod, FactMetric,
)

PUBLIC = "public"
# Postgres caps a statement at 65,535 bind params; widest table ~20 cols -> keep small.
BATCH = 1000

# The state directory that carries the CDS<->NCES crosswalk ('Fed ID') plus the rich
# attributes dim_school wants (charter/Title I/DASS/locale/enrollment/demographics).
DIRECTORY_FILE = "directory/public-schools_2024-25.csv"

# CDE reports some non-school aggregates at Aggregate Level 'S': a school code of
# 0000000 is a *District Office* row, 0000001 a *Nonpublic, Nonsectarian* placement
# bucket. Neither is a real school (nor has an NCES id) — they are excluded.
NON_SCHOOL_CODES = {"0000000", "0000001"}

# --------------------------------------------------------------------------- #
# Conformed vocabulary
#
# STUDENT_GROUPS / METRICS moved to core (`app/vocab.py`) 2026-07-15 — sip needs them too, and
# a vocabulary two modules must agree on can't live inside one of them. Re-exported below so the
# CA loaders read unchanged; import them from `app.vocab` in new code.
#
# What stays here is CA's mapping INTO that vocabulary (CDE_CATEGORY) plus CA's periods. That's
# the conformed/adapter line: another state brings its own crosswalk and reuses the same ids.
# --------------------------------------------------------------------------- #
from app.vocab import METRICS, STUDENT_GROUPS  # noqa: F401  (re-exported for the CA loaders)

# CDE ReportingCategory -> conformed student_group_id. Grade-span codes (GR*) and
# anything not here are skipped (a different axis, not a student group).
CDE_CATEGORY = {
    "TA": "all",
    "RB": "race_black", "RI": "race_amerind", "RA": "race_asian", "RF": "race_filipino",
    "RH": "race_hispanic", "RP": "race_pacific", "RT": "race_two", "RW": "race_white",
    "RD": "race_nr",
    "GF": "gender_f", "GM": "gender_m", "GX": "gender_x",
    "SE": "el", "SD": "swd", "SS": "sed", "SM": "migrant", "SF": "foster", "SH": "homeless",
    # Newer CALPADS scheme (census enrollment; also sped/foster). No key collisions
    # with the older codes above. ELAS_* (English-status) and AR_* (age) are left
    # unmapped on purpose — different axes / redundant with SG_EL.
    "RE_B": "race_black", "RE_I": "race_amerind", "RE_A": "race_asian", "RE_F": "race_filipino",
    "RE_H": "race_hispanic", "RE_P": "race_pacific", "RE_T": "race_two", "RE_W": "race_white",
    "RE_D": "race_nr",
    "GN_M": "gender_m", "GN_F": "gender_f", "GN_X": "gender_x",
    "SG_SD": "swd", "SG_DS": "sed", "SG_EL": "el",   # SD=disabilities, DS=disadvantaged (inferred)
    "SG_HM": "homeless", "SG_FS": "foster", "SG_MG": "migrant",
}

PERIODS = [
    ("p2021-22", "annual", "2021-22", "2021-22"),
    ("p2022-23", "annual", "2022-23", "2022-23"),
    ("p2023-24", "annual", "2023-24", "2023-24"),
    ("p2024-25", "annual", "2024-25", "2024-25"),
]


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #
def _f(s):
    s = (s or "").strip()
    if s in ("", "*", "N/A", "NA", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(s):
    v = _f(s)
    return int(v) if v is not None else None


def _b(s):
    return (s or "").strip().lower() in ("y", "yes", "true", "1")


def cds_from(county, district, school):
    return f"{(county or '').strip().zfill(2)}{(district or '').strip().zfill(5)}{(school or '').strip().zfill(7)}"


def nces_ids(cds, xwalk):
    """Map a 14-digit CA CDS onto the federal keys: (school_id, district_id).

    `school_id` is the 12-digit NCES 'Fed ID'; `district_id` its 7-digit LEAID prefix.
    When a school has no NCES id yet (mostly newly-opened charters), fall back to a
    state-scoped 'CA-<cds>' id so no facts are lost — self-evidently not federal, and
    it can't collide with a real ncessch. A crosswalk refresh later upgrades it.
    """
    fed = xwalk.get(cds)
    if fed:
        return fed, fed[:7]
    return f"CA-{cds}", f"CA-{cds[:7]}"


def field(r, *names):
    """First present column among candidates. CDE is inconsistent about spaces:
    'Reporting Category' (chronic) vs 'ReportingCategory' (suspension/ACGR)."""
    for n in names:
        v = r.get(n)
        if v is not None:
            return v
    return None


# --- source access: local paths OR gs:// URIs (via fsspec/gcsfs) --------------
def _join(base, rel):
    b = str(base)
    return b.rstrip("/") + "/" + rel if b.startswith("gs://") else str(pathlib.Path(base) / rel)


def _open(path, encoding):
    return fsspec.open(str(path), mode="r", encoding=encoding, newline="")


def _exists(path):
    fs, p = fsspec.core.url_to_fs(str(path))
    return fs.exists(p)


def _basename(path):
    return str(path).rstrip("/").rsplit("/", 1)[-1]


# --------------------------------------------------------------------------- #
# DB
# --------------------------------------------------------------------------- #
def _engine():
    return create_engine(settings.migration_database_url)


# --------------------------------------------------------------------------- #
# seeding (seed_ca_dims.py)
# --------------------------------------------------------------------------- #
def seed_reference(conn):
    conn.execute(pg_insert(DimStudentGroup).values(
        [dict(student_group_id=i, label=l, dimension=d) for i, l, d in STUDENT_GROUPS]
    ).on_conflict_do_nothing())
    conn.execute(pg_insert(GroupCrosswalk).values(
        [dict(source_system="cde_reportingcategory", source_code=c, student_group_id=g)
         for c, g in CDE_CATEGORY.items()]
    ).on_conflict_do_nothing())
    conn.execute(pg_insert(DimMetric).values(METRICS).on_conflict_do_nothing())
    conn.execute(pg_insert(DimPeriod).values(
        [dict(period_id=p, grain=g, school_year=y, label=lbl, tenant_id=PUBLIC, visibility=PUBLIC)
         for p, g, y, lbl in PERIODS]
    ).on_conflict_do_nothing())
    print(f"  seeded: {len(STUDENT_GROUPS)} groups, {len(CDE_CATEGORY)} crosswalk, "
          f"{len(METRICS)} metrics, {len(PERIODS)} periods")


def load_crosswalk(data_dir):
    """CDS -> NCES 'Fed ID' map, read once from the state directory (DIRECTORY_FILE)."""
    path = _join(data_dir, DIRECTORY_FILE)
    x = {}
    if not _exists(path):
        print(f"  WARNING: crosswalk {_basename(path)} not found — every school gets a CA- id")
        return x
    with _open(path, "utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            cds = (r.get("CDS Code") or "").strip()
            fed = (r.get("Fed ID") or "").strip()
            if cds and fed:
                x[cds] = fed
    print(f"  crosswalk: {len(x)} CDS->NCES")
    return x


def load_schools(conn, path, dry):
    """dim_school from the state directory. Keyed on NCES; CDS rides as state_*_id."""
    n, n_syn, n_agg, rows = 0, 0, 0, []
    with _open(path, "utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            cds = (r.get("CDS Code") or "").strip()
            if not cds:
                continue
            if cds[7:] in NON_SCHOOL_CODES:          # district office / NPS aggregate
                n_agg += 1
                continue
            fed = (r.get("Fed ID") or "").strip()
            school_id, district_id = nces_ids(cds, {cds: fed} if fed else {})
            if not fed:
                n_syn += 1
            rows.append(dict(
                school_id=school_id, district_id=district_id,
                state_school_id=cds, state_district_id=cds[:7],
                school_year=r.get("Academic Year"), school_name=r.get("School Name"),
                district_name=r.get("District Name"), county_name=r.get("County Name"),
                school_level=r.get("School Level"), grade_low=r.get("Grade Low"),
                grade_high=r.get("Grade High"), is_charter=_b(r.get("Charter")),
                is_title_i=_b(r.get("Title I")), is_dass=_b(r.get("DASS")),
                locale=r.get("Locale"), enroll_total=_i(r.get("Enroll Total")),
                pct_sed=_f(r.get("Socioeconomically Disadvantaged (%)")),
                pct_el=_f(r.get("English Learner (%)")),
                pct_swd=_f(r.get("Students with Disabilities (%)")),
                latitude=_f(r.get("Latitude")), longitude=_f(r.get("Longitude")),
            ))
            n += 1
            if not dry and len(rows) >= BATCH:
                _upsert_schools(conn, rows); rows = []
        if not dry and rows:
            _upsert_schools(conn, rows)
    print(f"  dim_school: {n} schools ({n - n_syn} NCES-keyed, {n_syn} CA- fallback), "
          f"{n_agg} non-school aggregates excluded")


def _upsert_schools(conn, rows):
    stmt = pg_insert(DimSchool).values(rows)
    cols = {c.name: c for c in stmt.excluded if c.name != "school_id"}
    conn.execute(stmt.on_conflict_do_update(index_elements=["school_id"], set_=cols))


# --------------------------------------------------------------------------- #
# metric loading (load_ca_<fact>.py)
# --------------------------------------------------------------------------- #
def load_metric_file(conn, path, metric_id, period_id, value_col, n_col, xwalk, dry, where=None):
    facts, seen_schools = [], {}
    n_fact = n_roll = n_skip = n_agg = 0
    syn = set()                                  # distinct CA- fallback schools
    src = _basename(path)
    with _open(path, "latin-1") as fh:      # CDE files are Latin-1
        for r in csv.DictReader(fh, delimiter="\t"):
            grp = CDE_CATEGORY.get((field(r, "Reporting Category", "ReportingCategory") or "").strip())
            if grp is None:                                     # grade span / unmapped
                n_skip += 1
                continue
            if (field(r, "Aggregate Level", "AggregateLevel") or "").strip() != "S":  # rollups deferred
                n_roll += 1
                continue
            school_code = (field(r, "School Code", "SchoolCode") or "").strip().zfill(7)
            if school_code in NON_SCHOOL_CODES:                 # district office / NPS aggregate, not a school
                n_agg += 1
                continue
            # optional row filter (e.g. CGR's CompleterType='TA' total, to avoid split-key dups)
            if where and any((field(r, k) or "").strip() != v for k, v in where.items()):
                n_skip += 1
                continue
            raw = r.get(value_col)
            value = _f(raw)
            status = "reported" if value is not None else ("suppressed" if (raw or "").strip() == "*" else "not_collected")
            cds = cds_from(field(r, "County Code", "CountyCode"),
                           field(r, "District Code", "DistrictCode"), school_code)
            sid, did = nces_ids(cds, xwalk)
            if sid.startswith("CA-"):
                syn.add(sid)
            seen_schools.setdefault(sid, dict(
                school_id=sid, district_id=did,
                state_school_id=cds, state_district_id=cds[:7],
                county_name=field(r, "County Name", "CountyName"),
                district_name=field(r, "District Name", "DistrictName"),
                school_name=field(r, "School Name", "SchoolName")))
            facts.append(dict(
                school_id=sid, period_id=period_id, metric_id=metric_id, student_group_id=grp,
                tenant_id=PUBLIC, visibility=PUBLIC, value=value, value_status=status,
                n_size=_i(r.get(n_col)), source_dataset=src))
            n_fact += 1
            if not dry and len(facts) >= BATCH:
                _flush_facts(conn, list(seen_schools.values()), facts); facts, seen_schools = [], {}
    if not dry:
        _flush_facts(conn, list(seen_schools.values()), facts)
    print(f"  {src}: {n_fact} school facts ({len(syn)} schools on CA- fallback), "
          f"{n_agg} non-school aggregates excluded, {n_roll} rollups deferred, {n_skip} skipped")


def _flush_facts(conn, school_stubs, facts):
    if school_stubs:  # FK integrity for schools not in the directory
        conn.execute(pg_insert(DimSchool).values(school_stubs).on_conflict_do_nothing())
    if not facts:
        return
    # dedup within batch on the PK (last wins) so ON CONFLICT never touches a row twice
    dedup = {}
    for f in facts:
        dedup[(f["school_id"], f["period_id"], f["metric_id"], f["student_group_id"])] = f
    stmt = pg_insert(FactMetric).values(list(dedup.values()))
    conn.execute(stmt.on_conflict_do_update(
        index_elements=["school_id", "period_id", "metric_id", "student_group_id"],
        set_=dict(value=stmt.excluded.value, value_status=stmt.excluded.value_status,
                  n_size=stmt.excluded.n_size, source_dataset=stmt.excluded.source_dataset)))


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def _args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True,
                    help="raw data root: a local path or a gs://bucket/prefix URI")
    ap.add_argument("--dry-run", action="store_true", help="parse + count only, no DB writes")
    return ap.parse_args()


def run_seed():
    a = _args()
    schools = _join(a.data_dir, DIRECTORY_FILE)
    if a.dry_run:
        print("DRY RUN")
        if _exists(schools):
            load_schools(None, schools, dry=True)
        else:
            print(f"  (skip dim_school — {schools} not found)")
        return
    with _engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, false)"), {"t": PUBLIC})
        print("Seeding reference dimensions..."); seed_reference(conn)
        if _exists(schools):
            print("Loading dim_school..."); load_schools(conn, schools, dry=False)
        else:
            print(f"  SKIPPING dim_school — {schools} not uploaded yet. "
                  "Re-run this once directory/ is present to refresh it.")
    print("Done.")


def run_metric_loader(spec):
    """spec: dict(file, metric_id, period_id, value_col, n_col)."""
    a = _args()
    path = _join(a.data_dir, spec["file"])
    if a.dry_run:
        print("DRY RUN")
        xwalk = load_crosswalk(a.data_dir)
        load_metric_file(None, path, spec["metric_id"], spec["period_id"],
                         spec["value_col"], spec["n_col"], xwalk, dry=True, where=spec.get("where"))
        return
    with _engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, false)"), {"t": PUBLIC})
        print(f"Loading {spec['metric_id']} from {spec['file']}...")
        xwalk = load_crosswalk(a.data_dir)
        load_metric_file(conn, path, spec["metric_id"], spec["period_id"],
                         spec["value_col"], spec["n_col"], xwalk, dry=False, where=spec.get("where"))
    print("Done.")
