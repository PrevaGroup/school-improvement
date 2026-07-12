# CA public-data loaders

California state (public-tier) loaders. Naming convention: **`load_<state>_<fact>.py`**
(here `load_ca_<fact>.py`). Each fact gets its own thin script defining a `SPEC`;
shared machinery lives in [`_shared.py`](_shared.py). Everything loads into the
**public** tier (`tenant_id='public'`).

## Run order

Seed the conformed dimensions + `dim_school` **once**, then run any fact loaders:

```bash
python -m etl.ca.seed_ca_dims                --data-dir ~/raw
python -m etl.ca.load_ca_chronic_absenteeism --data-dir ~/raw
python -m etl.ca.load_ca_suspension          --data-dir ~/raw
python -m etl.ca.load_ca_expulsion           --data-dir ~/raw
python -m etl.ca.load_ca_graduation          --data-dir ~/raw
python -m etl.ca.load_ca_stability           --data-dir ~/raw
python -m etl.ca.load_ca_college_going        --data-dir ~/raw
python -m etl.ca.load_ca_homeless            --data-dir ~/raw
python -m etl.ca.load_ca_enrollment          --data-dir ~/raw
```
Add `--dry-run` to parse + count without writing.

## Scripts

| Script | metric_id | Period | Source file | ~rows |
|---|---|---|---|---|
| `seed_ca_dims.py` | — (dims + dim_school) | — | `directory/schools_2025-26.csv` | 9,946 schools |
| `load_ca_chronic_absenteeism.py` | `chronic_absenteeism_rate` | 2023‑24 | `attendance/chronicabsenteeism_2023-24.txt` | 173,574 |
| `load_ca_suspension.py` | `suspension_rate` | 2023‑24 | `behavior/suspension_2023-24.txt` | 180,794 |
| `load_ca_expulsion.py` | `expulsion_rate` | 2023‑24 | `behavior/expulsion_2023-24.txt` | 180,794 |
| `load_ca_graduation.py` | `grad_rate_acgr` | 2024‑25 | `academics/acgr_gradcohort_2024-25.txt` | 47,142 |
| `load_ca_stability.py` | `stability_rate` | 2023‑24 | `demographics/mobility_stability_2023-24.txt` | 181,778 |
| `load_ca_college_going.py` | `college_going_rate` | 2021‑22 | `academics/collegegoingrate_16mo_2021-22.txt` | 31,224 |
| `load_ca_homeless.py` | `homeless_enrollment` | 2023‑24 | `demographics/homeless_2023-24.txt` | 10,669 |
| `load_ca_enrollment.py` | `enrollment` | 2024‑25 | `demographics/enrollment_censusday_2024-25.txt` | 154,538 |

To add another same-shape metric, copy a script and change the `SPEC` (add the metric
to `METRICS` / any new period to `PERIODS` in `_shared.py`). Use `where={col: val}` in a
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

- Two CDE subgroup code schemes are conformed in `_shared.CDE_CATEGORY`: the older
  `RB/GF/SD` (discipline, chronic, ACGR) and the newer CALPADS `RE_H/GN_M/SG_EL` (census
  enrollment). No collisions.
- Loaders connect as `sip_migrator` (Secret Manager) and `SET app.tenant='public'`.
- CDE demo-download `.txt` files are **Latin-1**; the directory CSV is UTF-8. CDE is also
  inconsistent about column spacing (`Reporting Category` vs `ReportingCategory`) — handled.
- Batches are 1,000 rows (Postgres 65,535 bind-param/statement limit); facts are
  de-duplicated per batch so `ON CONFLICT` never touches a row twice.
