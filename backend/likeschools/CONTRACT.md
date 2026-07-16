# likeschools — CONTRACT

The matching **engine**. No serving surface. Rewrite the algorithm however you like — different
distance, different features, a different method entirely — and nothing downstream notices, as
long as this contract holds.

## Tables owned (declares AND writes; all public, no RLS)

| Table | Role |
|---|---|
| `mart_school_peer` | **THE seam.** `serving` reads it with SQL. Columns: `school_id`, `peer_school_id`, `school_year`, `rank` (1 = nearest), `distance`, `level_bucket`, `low_confidence`. Shape changes are contract changes: update DDL + models + every reader together |
| `feat_match_vector` | the standardized match vector per school (inputs + `n_imputed`) |
| `model_partition_stats` | run provenance. `precision_mat` is row-major flattened; reshape to `(len(feature_names), len(feature_names))` — tested |

Models: `likeschools/models.py`.

## Migration revisions owned

`0004_peer_tables` — lives in `likeschools/migrations/`, wired via `alembic.ini`
`version_locations`. A revision file outside a listed path is invisible to Alembic — a migration
that silently never runs.

## Reads

`dim_school` **input** demographics only: `pct_sed`, `pct_el`, `pct_swd`, `enroll_total`,
`locale`, `school_level`, `school_year`.

## Invariants (tested — `likeschools/tests/`)

- **D1: never read outcomes.** No outcome in the match vector; the engine never selects from
  `fact_metric`. Match on an outcome and peer comparison goes circular.
- A school is never its own peer; `rank` follows distance; `k_eff = min(k, n-1)`.
- `low_confidence` = `n_imputed > 2` OR thin partition OR kth-distance above the run percentile.
- Suppression/missing never coerced to a value: missing features are imputed to the
  within-partition median and *counted* (`n_imputed`), not zeroed.

## Entry point

`python -m likeschools.build_peers [--k 50] [--year Y] [--conf-pctile 90] [--dry-run]`
(Cloud Shell; replaces a run-year's rows atomically: delete-then-insert per `school_year`.)

## Registration

`likeschools.models` must stay imported by `migrations/env.py`, `0001_initial_schema.py`, and
`scripts/gen_schema_reference.py` (else: silent DROP TABLE at autogenerate). Boundary-scanned via
`SOURCE_TREES`; tests listed in `pytest.ini`.
