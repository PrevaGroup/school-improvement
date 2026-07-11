# CA public-data loaders

California state (public-tier) loaders. Naming convention: **`load_<state>_<fact>.py`**
(here `load_ca_<fact>.py`). Each fact gets its own thin script defining a `SPEC`;
shared machinery lives in [`_shared.py`](_shared.py). Everything loads into the
**public** tier (`tenant_id='public'`).

## Run order

Seed the conformed dimensions + `dim_school` **once**, then run any fact loaders:

```bash
python -m etl.ca.seed_ca_dims             --data-dir ~/data
python -m etl.ca.load_ca_chronic_absenteeism --data-dir ~/data
python -m etl.ca.load_ca_suspension       --data-dir ~/data
python -m etl.ca.load_ca_expulsion        --data-dir ~/data
python -m etl.ca.load_ca_graduation       --data-dir ~/data
```
Add `--dry-run` to any of them to parse + count without writing.

## Scripts

| Script | Loads | metric_id | Period | Source file |
|---|---|---|---|---|
| `seed_ca_dims.py` | student groups + crosswalk, metrics, periods, **dim_school** | — | — | `directory/schools_2025-26.csv` |
| `load_ca_chronic_absenteeism.py` | chronic absenteeism | `chronic_absenteeism_rate` | 2023‑24 | `attendance/chronicabsenteeism_2023-24.txt` |
| `load_ca_suspension.py` | suspension rate | `suspension_rate` | 2023‑24 | `behavior/suspension_2023-24.txt` |
| `load_ca_expulsion.py` | expulsion rate | `expulsion_rate` | 2023‑24 | `behavior/expulsion_2023-24.txt` |
| `load_ca_graduation.py` | ACGR graduation rate | `grad_rate_acgr` | 2024‑25 | `academics/acgr_gradcohort_2024-25.txt` |

These four share the CDE `school × reporting-category × rate` shape, so each is a
~10-line `SPEC`. To add another same-shape metric, copy one and change the `SPEC`
(and add the metric to `METRICS` / any new period to `PERIODS` in `_shared.py`).

## Pending (need a loader variant, not just a SPEC)

| Fact | Why it's different |
|---|---|
| College-Going Rate | extra `CompleterType` split dimension — needs a filter to the "all" total |
| Absence-by-reason | multiple rate columns per row (one metric per reason) |
| CAASPP ELA/Math | caret-delimited, zipped ~1 GB, numeric subgroup ids, `% met` / distance-from-standard |
| Enrollment / FRPM / homeless / SpEd | `.xlsx` or different columns; some feed `dim_school` attrs |
| SACS financials | Access `.mdb`, **district** grain (goes to a finance fact/ref) |
| Rollups (T/C/D) | all loaders currently **defer** these; they belong in `ref_benchmark` and need an "all schools" filter (charter/DASS variants collide on the key) |

## Notes

- Loaders connect as `sip_migrator` (Secret Manager) and `SET app.tenant='public'`.
- CDE demo-download `.txt` files are **Latin-1**; the directory CSV is UTF-8.
- Batches are 1,000 rows (Postgres 65,535 bind-param/statement limit); facts are
  de-duplicated per batch so `ON CONFLICT` never touches a row twice.
