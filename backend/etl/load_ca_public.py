"""Load CA public (state) data into the star schema.

All rows go into the PUBLIC tier (tenant_id='public'). Seeds the conformed
dimensions, then loads metric files: school rows -> fact_metric, and the
state/county/district rollup rows -> ref_benchmark.

Run (connects as sip_migrator, reads passwords from Secret Manager via config):
    python -m etl.load_ca_public --data-dir /path/to/California/raw
    python -m etl.load_ca_public --data-dir /path/to/California/raw --dry-run   # parse only

Extend by adding entries to METRIC_FILES.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.models import (
    Base, DimSchool, DimStudentGroup, GroupCrosswalk, DimMetric, DimPeriod,
    FactMetric, RefBenchmark,
)

PUBLIC = "public"
# Rows per INSERT. Postgres caps a statement at 65,535 bind parameters, and the
# widest table (dim_school) has ~20 columns -> keep batch * columns well under that.
BATCH = 1000

# --------------------------------------------------------------------------- #
# Conformed vocabulary
# --------------------------------------------------------------------------- #
STUDENT_GROUPS = [
    ("all", "All Students", "total"),
    ("race_black", "Black/African American", "race"),
    ("race_amerind", "American Indian/Alaska Native", "race"),
    ("race_asian", "Asian", "race"),
    ("race_filipino", "Filipino", "race"),
    ("race_hispanic", "Hispanic/Latino", "race"),
    ("race_pacific", "Pacific Islander", "race"),
    ("race_two", "Two or More Races", "race"),
    ("race_white", "White", "race"),
    ("race_nr", "Not Reported", "race"),
    ("gender_f", "Female", "gender"),
    ("gender_m", "Male", "gender"),
    ("gender_x", "Non-Binary", "gender"),
    ("el", "English Learners", "eng_prof"),
    ("swd", "Students with Disabilities", "program"),
    ("sed", "Socioeconomically Disadvantaged", "ses"),
    ("migrant", "Migrant", "program"),
    ("foster", "Foster Youth", "program"),
    ("homeless", "Homeless", "program"),
]

# CDE ReportingCategory -> conformed student_group_id. Grade-span codes (GR*) and
# anything not here are skipped (they're a different axis, not a student group).
CDE_CATEGORY = {
    "TA": "all",
    "RB": "race_black", "RI": "race_amerind", "RA": "race_asian", "RF": "race_filipino",
    "RH": "race_hispanic", "RP": "race_pacific", "RT": "race_two", "RW": "race_white",
    "RD": "race_nr",
    "GF": "gender_f", "GM": "gender_m", "GX": "gender_x",
    "SE": "el", "SD": "swd", "SS": "sed", "SM": "migrant", "SF": "foster", "SH": "homeless",
}

METRICS = [
    dict(metric_id="chronic_absenteeism_rate", domain="attendance", display_name="Chronic Absenteeism Rate",
         unit="pct", direction="lower_better", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=True, data_origin="state"),
    dict(metric_id="suspension_rate", domain="behavior", display_name="Suspension Rate (Total)",
         unit="pct", direction="lower_better", grains="annual", applies_to_levels="ES,MS,HS",
         is_leading_indicator=True, data_origin="state"),
]

PERIODS = [
    ("p2022-23", "annual", "2022-23", "2022-23"),
    ("p2023-24", "annual", "2023-24", "2023-24"),
    ("p2024-25", "annual", "2024-25", "2024-25"),
]

# Metric files: (relpath, metric_id, period_id, value_col, n_col). Tab-delimited CDE files.
METRIC_FILES = [
    ("attendance/chronicabsenteeism_2023-24.txt", "chronic_absenteeism_rate", "p2023-24",
     "ChronicAbsenteeismRate", "ChronicAbsenteeismEligibleCumulativeEnrollment"),
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


# --------------------------------------------------------------------------- #
# loaders
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


def load_schools(conn, path, dry):
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = []
        for r in csv.DictReader(fh):
            cds = (r.get("CDS Code") or "").strip()
            if not cds:
                continue
            rows.append(dict(
                school_id=cds, cds_code=cds, school_year=r.get("Academic Year"),
                school_name=r.get("School Name"), district_id=cds[:7],
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
    print(f"  dim_school: {n} schools")


def _upsert_schools(conn, rows):
    stmt = pg_insert(DimSchool).values(rows)
    cols = {c.name: c for c in stmt.excluded if c.name != "school_id"}
    conn.execute(stmt.on_conflict_do_update(index_elements=["school_id"], set_=cols))


def load_metric_file(conn, path, metric_id, period_id, value_col, n_col, dry):
    facts, benchmarks, seen_schools = [], [], {}
    n_fact = n_bench = n_skip = 0
    # CDE demo-download files are Latin-1 (e.g. 'ñ' in school names), not UTF-8.
    with open(path, encoding="latin-1", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for r in reader:
            cat = (r.get("Reporting Category") or "").strip()
            grp = CDE_CATEGORY.get(cat)
            if grp is None:              # grade spans / unmapped -> skip
                n_skip += 1
                continue
            level = (r.get("Aggregate Level") or "").strip()
            raw = r.get(value_col)
            value = _f(raw)
            status = "reported" if value is not None else ("suppressed" if (raw or "").strip() == "*" else "not_collected")
            n_size = _i(r.get(n_col))
            if level != "S":
                # Rollup rows (T/C/D) -> ref_benchmark are DEFERRED: CDE splits them
                # into charter/DASS variants that collide on the benchmark key. Reload
                # with an "all schools" filter when the benchmarking step is built.
                n_bench += 1
                continue
            sid = cds_from(r.get("County Code"), r.get("District Code"), r.get("School Code"))
            seen_schools.setdefault(sid, dict(
                school_id=sid, cds_code=sid, county_name=r.get("County Name"),
                district_name=r.get("District Name"), school_name=r.get("School Name"),
                district_id=sid[:7]))
            facts.append(dict(
                school_id=sid, period_id=period_id, metric_id=metric_id, student_group_id=grp,
                tenant_id=PUBLIC, visibility=PUBLIC, value=value, value_status=status,
                n_size=n_size, source_dataset=path.name))
            n_fact += 1
            if not dry and len(facts) >= BATCH:
                _flush_facts(conn, list(seen_schools.values()), facts); facts, seen_schools = [], {}
            if not dry and len(benchmarks) >= BATCH:
                _flush_benchmarks(conn, benchmarks); benchmarks = []
    if not dry:
        _flush_facts(conn, list(seen_schools.values()), facts)
        _flush_benchmarks(conn, benchmarks)
    print(f"  {path.name}: {n_fact} school facts loaded, {n_bench} rollup rows deferred, "
          f"{n_skip} skipped (grade-span/unmapped)")


def _flush_facts(conn, school_stubs, facts):
    if school_stubs:  # ensure FK integrity for schools not in the directory
        conn.execute(pg_insert(DimSchool).values(school_stubs).on_conflict_do_nothing())
    if facts:
        stmt = pg_insert(FactMetric).values(facts)
        conn.execute(stmt.on_conflict_do_update(
            index_elements=["school_id", "period_id", "metric_id", "student_group_id"],
            set_=dict(value=stmt.excluded.value, value_status=stmt.excluded.value_status,
                      n_size=stmt.excluded.n_size, source_dataset=stmt.excluded.source_dataset)))


def _flush_benchmarks(conn, rows):
    if rows:
        stmt = pg_insert(RefBenchmark).values(rows)
        conn.execute(stmt.on_conflict_do_update(
            index_elements=["level", "entity_id", "period_id", "metric_id", "student_group_id"],
            set_=dict(value=stmt.excluded.value, n_size=stmt.excluded.n_size)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="California/raw directory")
    ap.add_argument("--dry-run", action="store_true", help="parse + count only, no DB writes")
    args = ap.parse_args()
    root = pathlib.Path(args.data_dir)

    if args.dry_run:
        print("DRY RUN (no DB writes)")
        load_schools(None, root / "directory/schools_2025-26.csv", dry=True)
        for rel, mid, pid, vcol, ncol in METRIC_FILES:
            load_metric_file(None, root / rel, mid, pid, vcol, ncol, dry=True)
        return

    engine = create_engine(settings.migration_database_url)
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, false)"), {"t": PUBLIC})
        print("Seeding reference dimensions...")
        seed_reference(conn)
        print("Loading dim_school...")
        load_schools(conn, root / "directory/schools_2025-26.csv", dry=False)
        for rel, mid, pid, vcol, ncol in METRIC_FILES:
            print(f"Loading {rel}...")
            load_metric_file(conn, root / rel, mid, pid, vcol, ncol, dry=False)
    print("Done.")


if __name__ == "__main__":
    main()
