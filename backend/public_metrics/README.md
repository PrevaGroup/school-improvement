# public_metrics — California public-data ETL (scaffold)

> **SCAFFOLD / MAP ONLY — no code has moved here yet.** This documents where the feature's code
> currently lives. Relocation is a later step (see `docs/MODULES.md`). Import from the paths below.

Bulk ETL that loads CDE / data.ca.gov public files into the star schema as `fact_metric` rows at
`tenant_id='public'` (~960k rows across eight public metrics). Per-fact loaders are thin: each
defines a SPEC and calls the shared runner.

## Component map (where the code is today)

| Concern | File(s) | Notes |
|---|---|---|
| Shared loader machinery | `backend/etl/ca/_shared.py` | `run_metric_loader`, `load_metric_file`, conformed vocab constants |
| Per-fact loaders (×8) | `backend/etl/ca/load_ca_*.py` | chronic_absenteeism, college_going, enrollment, expulsion, graduation, homeless, stability, suspension |
| Dimension seed | `backend/etl/ca/seed_ca_dims.py` | seeds `dim_*` |
| Pipeline docs | `backend/etl/ca/README.md`, `docs/DATA_CATALOG.md`, `docs/download_log.txt`, `docs/caaspp_download_log.txt`, `docs/sacs_staffing_log.txt` | |

## Contract

- **Writes:** `fact_metric` @ `tenant_id='public'` (and seeds shared `dim_*` via `seed_ca_dims`).
- **Reads:** raw CDE/CA files (local or `gs://`); the conformed vocabulary in `core`.
- **Owns no private tables.** No serving API — this is offline ETL.
- **Note / coupling:** `seed_ca_dims.py` writes shared `core` dimensions. Seeding the shared
  schema is close to a `core` concern; treat dimension-shape changes as `core` changes.

## Boundary

Depends only on `core`. Must not import from other feature modules. Adding a new public metric =
a new `load_ca_<fact>.py` + SPEC; it should not require touching another module.
