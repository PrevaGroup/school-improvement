"""CA CAASPP Smarter Balanced ELA + Math -> fact_metric (2023-24 and 2024-25).

    python -m public_metrics.load_ca_caaspp --data-dir gs://<bucket>/raw/ca [--dry-run]

This is the "loader variant" the README's Pending table promised — the research files
differ from the CDE demo-download shape in every axis `load_metric_file` assumes:

- **caret-delimited** (`^`), not tab, and shipped **zipped** (~157 MB zip -> ~1 GB txt).
  Streamed straight out of the zip member; nothing is unpacked to disk.
- **numeric student-group ids** (ETS Table A), not ReportingCategory codes ->
  `_shared.CAASPP_GROUP`.
- **two metrics in one file**: Test ID 1 = ELA, 2 = Math. One pass emits both — the file
  is ~3M rows/year, reading it twice would be rude.
- **a grade axis**: rows are school x grade x group x test. Only the **Grade 13
  (All Grades) rollup** fits the conformed grain (school x period x metric x group).
  Mean scale score is NOT loaded: at the all-grades rollup it averages across different
  grade scales, so it isn't a number. Distance-from-standard needs per-grade thresholds
  that aren't in the file. Both stay future work (per-grade facts would need a grade
  axis on the grain — a core question, not a loader flag).
- **no name columns** — codes only. The `entities` lookup member inside the same zip
  supplies county/district/school names for the dim_school stubs.

The measure loaded is **"Percentage Standard Met and Above"**; `n_size` is
"Students with Scores" (the percentage's denominator). Suppression: ETS marks small
cells with `*`, same convention `_f` already maps to None -> `value_status`.
"""
from __future__ import annotations

import csv
import io
import zipfile

import fsspec
from sqlalchemy import text

from ._shared import (
    BATCH, CAASPP_GROUP, NON_SCHOOL_CODES, PUBLIC,
    _args, _basename, _engine, _f, _flush_facts, _i, _join,
    cds_from, field, load_crosswalk, nces_ids,
)

SPECS = [
    dict(file="academics/caaspp_smarterbalanced_all_2023-24.zip", period_id="p2023-24"),
    dict(file="academics/caaspp_smarterbalanced_all_2024-25.zip", period_id="p2024-25"),
]

TEST_METRIC = {"1": "ela_met_standard_pct", "2": "math_met_standard_pct"}
ALL_GRADES = "13"
VALUE_COL = "Percentage Standard Met and Above"
N_COL = "Students with Scores"


def _norm_id(s):
    """'001' / ' 1 ' -> '1'; non-numeric -> None. ETS zero-pads the numeric ids."""
    s = (s or "").strip()
    try:
        return str(int(s))
    except ValueError:
        return None


def pick_member(infos):
    """The data member = the largest .txt/.csv in the zip that isn't the entities lookup."""
    cands = [i for i in infos
             if i.filename.lower().endswith((".txt", ".csv"))
             and "entit" not in i.filename.lower()]
    if not cands:
        raise FileNotFoundError("no data member (.txt/.csv) found in zip")
    return max(cands, key=lambda i: i.file_size).filename


def load_entities(zf):
    """cds -> (county, district, school name) from the entities member, if present."""
    ent = [i for i in zf.infolist()
           if "entit" in i.filename.lower() and i.filename.lower().endswith((".txt", ".csv"))]
    names = {}
    if not ent:
        return names
    with zf.open(ent[0].filename) as bf:
        rdr = csv.DictReader(io.TextIOWrapper(bf, encoding="latin-1", newline=""), delimiter="^")
        for r in rdr:
            cds = cds_from(field(r, "County Code", "CountyCode"),
                           field(r, "District Code", "DistrictCode"),
                           field(r, "School Code", "SchoolCode"))
            names[cds] = (field(r, "County Name", "CountyName"),
                          field(r, "District Name", "DistrictName"),
                          field(r, "School Name", "SchoolName"))
    return names


def iter_caaspp_facts(rows, period_id, xwalk, names, counters, source):
    """Yield (school_stub, fact) per qualifying row. Pure — feed it any dict iterable.

    counters keys: fact, grade (non-13), roll (county/district/state rollups),
    agg (non-school codes), skip (unmapped group / test).
    """
    for r in rows:
        metric_id = TEST_METRIC.get(_norm_id(field(r, "Test ID", "Test Id", "TestID")) or "")
        if metric_id is None:                                     # CAST etc. — not SB
            counters["skip"] += 1
            continue
        if (r.get("Grade") or "").strip().lstrip("0") != ALL_GRADES:
            counters["grade"] += 1
            continue
        grp = CAASPP_GROUP.get(_norm_id(field(r, "Student Group ID", "Subgroup ID")) or "")
        if grp is None:                                           # different axis / complement
            counters["skip"] += 1
            continue
        school_code = (field(r, "School Code", "SchoolCode") or "").strip().zfill(7)
        if school_code == "0000000":                              # state/county/district rollup
            counters["roll"] += 1
            continue
        if school_code in NON_SCHOOL_CODES:                       # NPS placement bucket
            counters["agg"] += 1
            continue
        raw = r.get(VALUE_COL)
        value = _f(raw)
        status = "reported" if value is not None else (
            "suppressed" if (raw or "").strip() == "*" else "not_collected")
        cds = cds_from(field(r, "County Code", "CountyCode"),
                       field(r, "District Code", "DistrictCode"), school_code)
        sid, did = nces_ids(cds, xwalk)
        county, district, school = names.get(cds, (None, None, None))
        stub = dict(school_id=sid, district_id=did,
                    state_school_id=cds, state_district_id=cds[:7],
                    county_name=county, district_name=district, school_name=school)
        fact = dict(school_id=sid, period_id=period_id, metric_id=metric_id,
                    student_group_id=grp, tenant_id=PUBLIC, visibility=PUBLIC,
                    value=value, value_status=status,
                    n_size=_i(r.get(N_COL)), source_dataset=source)
        counters["fact"] += 1
        yield stub, fact


def load_caaspp_zip(conn, path, period_id, xwalk, dry):
    """Open one research-file zip and load its Grade-13 school facts. Returns counters."""
    counters = dict(fact=0, grade=0, roll=0, agg=0, skip=0)
    facts, seen_schools = [], {}
    syn = set()
    with fsspec.open(str(path), mode="rb") as bf, zipfile.ZipFile(bf) as zf:
        member = pick_member(zf.infolist())
        names = load_entities(zf)
        src = f"{_basename(path)}!{member}"
        with zf.open(member) as data:
            rdr = csv.DictReader(io.TextIOWrapper(data, encoding="latin-1", newline=""),
                                 delimiter="^")
            for stub, fact in iter_caaspp_facts(rdr, period_id, xwalk, names, counters, src):
                if fact["school_id"].startswith("CA-"):
                    syn.add(fact["school_id"])
                seen_schools.setdefault(stub["school_id"], stub)
                facts.append(fact)
                if not dry and len(facts) >= BATCH:
                    _flush_facts(conn, list(seen_schools.values()), facts)
                    facts, seen_schools = [], {}
        if not dry:
            _flush_facts(conn, list(seen_schools.values()), facts)
    print(f"  {src}: {counters['fact']} school facts ({len(syn)} schools on CA- fallback), "
          f"{counters['agg']} non-school aggregates excluded, {counters['roll']} rollups deferred, "
          f"{counters['grade']} per-grade rows skipped (Grade 13 only), {counters['skip']} skipped")
    return counters


def run():
    a = _args()
    if a.dry_run:
        print("DRY RUN")
        xwalk = load_crosswalk(a.data_dir)
        for spec in SPECS:
            load_caaspp_zip(None, _join(a.data_dir, spec["file"]), spec["period_id"], xwalk, dry=True)
        return
    with _engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant', :t, false)"), {"t": PUBLIC})
        xwalk = load_crosswalk(a.data_dir)
        for spec in SPECS:
            print(f"Loading CAASPP ELA+Math from {spec['file']}...")
            load_caaspp_zip(conn, _join(a.data_dir, spec["file"]), spec["period_id"], xwalk, dry=False)
    print("Done.")


if __name__ == "__main__":
    run()
