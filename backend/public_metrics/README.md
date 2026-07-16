# public_metrics — California public-data ETL

Bulk ETL that loads CDE / data.ca.gov public files into the star schema as `fact_metric` rows at
`tenant_id='public'` (~960k rows across eight public metrics). Per-fact loaders are thin: each
defines a `SPEC` and calls the shared runner in [`_shared.py`](_shared.py). Naming convention:
**`load_<state>_<fact>.py`** (here `load_ca_<fact>.py`).

**Relocated 2026-07-15** from `backend/etl/ca/` — the code, the loaders, and this runbook now live
together. `etl/ca/` still exists as a bare package marker for `etl.ca.sip`, which is **sip**'s and
hasn't relocated yet.

> **The runbook commands changed.** `python -m etl.ca.<x>` → `python -m public_metrics.<x>`.

## Contract

- **Writes:** `fact_metric` @ `tenant_id='public'`, and the shared `dim_*` rows via `seed_ca_dims`.
- **Reads:** raw CDE/CA files (local or `gs://`); the conformed vocabulary from `core`
  (`app/vocab.py` → `METRICS`, `STUDENT_GROUPS`).
- **Owns no private tables. No serving API** — this is offline ETL.
- **Declares no tables.** `fact_metric` and the `dim_*` are `core`'s schema; this module writes
  their rows. That split is deliberate — see §4 of `ARCHITECTURE.md`.
- **Coupling worth knowing:** `seed_ca_dims.py` writes shared `core` dimensions. Seeding the
  shared schema is close to a `core` concern; treat dimension-*shape* changes as `core` changes.

## Boundary

Depends only on `core`, enforced by `backend/tests/test_module_boundaries.py`. Adding a public
metric = a new `load_ca_<fact>.py` + `SPEC`; it must not require touching another module.

**The vocabulary is `core`'s, not this module's.** `STUDENT_GROUPS` / `METRICS` moved to
`app/vocab.py` (2026-07-15) because sip needs them too — a vocabulary two modules must agree on
can't live inside one of them. `_shared.py` re-exports them so the loaders read unchanged; import
from `app.vocab` in new code. What stays here is CA's mapping *into* that vocabulary
(`CDE_CATEGORY`, `PERIODS`) — another state brings its own crosswalk and reuses the same ids.

## School identity — federal NCES key

Per `docs/TARGET_SCHEMA.md`, school identity keys on the **federal NCES id**, not the CA state
code. Every loader:

- reads a **CDS → NCES crosswalk** once from `directory/public-schools_2024-25.csv` (its `Fed ID`
  column is the 12-digit NCES `ncessch`; `CDS Code` is the 14-digit state code).
  `dim_school.school_id` = Fed ID, `district_id` = its 7-digit LEAID; the CDS rides alongside as
  `state_school_id` / `state_district_id`.
- **falls back to `CA-<cds>`** when a school has no NCES id yet — almost all of these are
  newly-opened charters awaiting an NCES assignment (~70 statewide). No facts are lost; the `CA-`
  prefix marks them as state-minted and a later crosswalk refresh upgrades them.
- **excludes non-school aggregates**: CDE reports District-Office rows (school code `0000000`) and
  Nonpublic/Nonsectarian placement buckets (`0000001`) at Aggregate Level `S`. They aren't schools
  and have no NCES id, so they're dropped (~718 rows).

Each run prints its NCES-keyed / `CA-` fallback / excluded-aggregate counts.

## Run order

Runs in **Cloud Shell**, never locally (it hits Cloud SQL and needs cloud credentials — CLAUDE.md).
From `backend/`. Seed the conformed dimensions + `dim_school` **once**, then run any fact loaders:

```bash
python -m public_metrics.seed_ca_dims                --data-dir gs://<bucket>/raw/ca
python -m public_metrics.load_ca_chronic_absenteeism --data-dir gs://<bucket>/raw/ca
python -m public_metrics.load_ca_suspension          --data-dir gs://<bucket>/raw/ca
python -m public_metrics.load_ca_expulsion           --data-dir gs://<bucket>/raw/ca
python -m public_metrics.load_ca_graduation          --data-dir gs://<bucket>/raw/ca
python -m public_metrics.load_ca_stability           --data-dir gs://<bucket>/raw/ca
python -m public_metrics.load_ca_college_going       --data-dir gs://<bucket>/raw/ca
python -m public_metrics.load_ca_homeless            --data-dir gs://<bucket>/raw/ca
python -m public_metrics.load_ca_enrollment          --data-dir gs://<bucket>/raw/ca
```

`--data-dir` accepts either a **local path** (`~/raw/ca`) or a **`gs://bucket/prefix` URI**. The raw
data is laid out by state — `raw/ca/<domain>/…`, `raw/tx/…` later — so the state segment lives in
the path, not the code. GCS access uses ADC (`gcloud auth application-default login`, or the Cloud
Run / Cloud Shell service account); no keys in the repo. Add `--dry-run` to parse + count without
writing.

## Scripts

| Script | metric_id | Period | Source file | ~rows |
|---|---|---|---|---|
| `seed_ca_dims.py` | — (dims + dim_school) | — | `directory/public-schools_2024-25.csv` | ~9,982 schools |
| `load_ca_chronic_absenteeism.py` | `chronic_absenteeism_rate` | 2023‑24 | `attendance/chronicabsenteeism_2023-24.txt` | 173,574 |
| `load_ca_suspension.py` | `suspension_rate` | 2023‑24 | `behavior/suspension_2023-24.txt` | 180,794 |
| `load_ca_expulsion.py` | `expulsion_rate` | 2023‑24 | `behavior/expulsion_2023-24.txt` | 180,794 |
| `load_ca_graduation.py` | `grad_rate_acgr` | 2024‑25 | `academics/acgr_gradcohort_2024-25.txt` | 47,142 |
| `load_ca_stability.py` | `stability_rate` | 2023‑24 | `demographics/mobility_stability_2023-24.txt` | 181,778 |
| `load_ca_college_going.py` | `college_going_rate` | 2021‑22 | `academics/collegegoingrate_16mo_2021-22.txt` | 31,224 |
| `load_ca_homeless.py` | `homeless_enrollment` | 2023‑24 | `demographics/homeless_2023-24.txt` | 10,669 |
| `load_ca_enrollment.py` | `enrollment` | 2024‑25 | `demographics/enrollment_censusday_2024-25.txt` | 154,538 |

Row counts above are the pre-NCES figures; the NCES re-key drops the non-school aggregate rows
(school code `0000000`/`0000001`), so live counts run slightly lower.

To add another same-shape metric, copy a script and change the `SPEC`. A **new metric id** also
goes in `app/vocab.py` (`core` — additive is safe; renaming an id orphans existing `fact_metric`
rows and needs a migration); a **new period** goes in `PERIODS` here. Use `where={col: val}` in a
SPEC to filter a split dimension to its total (see `load_ca_college_going.py`).

## Pending (need a loader variant, not just a SPEC)

| Fact | Why it's different |
|---|---|
| CAASPP ELA/Math | caret-delimited, zipped ~1 GB, numeric subgroup ids, `% met` / distance-from-standard |
| SACS financials | Access `.mdb`, **district** grain |
| Absence-by-reason | several count columns per row (one metric per reason) |
| SpEd by disability | `ReportingCategory` is disability type + an `A` aggregate level |
| Foster-youth grad | mostly redundant with ACGR's `foster` subgroup; other categories are intersections |
| FRPM / ESSA PPE | `.xlsx` |
| Rollups (T/C/D) | all loaders **defer** these; they belong in `ref_benchmark` and need an "all schools" filter (charter/DASS variants collide on the key) |

## Notes

- Two CDE subgroup code schemes are conformed in `_shared.CDE_CATEGORY`: the older `RB/GF/SD`
  (discipline, chronic, ACGR) and the newer CALPADS `RE_H/GN_M/SG_EL` (census enrollment). No
  collisions.
- Loaders connect as `sip_migrator` (Secret Manager) and `SET app.tenant='public'`.
- CDE demo-download `.txt` files are **Latin-1**; the directory CSV is UTF-8. CDE is also
  inconsistent about column spacing (`Reporting Category` vs `ReportingCategory`) — handled.
- Batches are 1,000 rows (Postgres 65,535 bind-param/statement limit); facts are de-duplicated per
  batch so `ON CONFLICT` never touches a row twice.
- **This module has no tests.** The loaders are SPEC-driven and DB-bound; the parsing helpers in
  `_shared.py` (`_f`, `_i`, `_b`, `field`, `cds_from`, `nces_ids`) are pure and would be the
  cheapest place to start. Add `backend/public_metrics/tests/` to `pytest.ini`'s `testpaths` when
  you do, or it will silently never run.

## Related docs

`docs/DATA_CATALOG.md` (raw sources and how they were obtained), `docs/download_log.txt`,
`docs/caaspp_download_log.txt`, `docs/sacs_staffing_log.txt`.
