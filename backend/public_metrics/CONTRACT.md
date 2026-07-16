# public_metrics — CONTRACT

Bulk ETL for California public data. Declares **no tables** and owns **no migrations** — its
entire contract is the *rows* it produces into core's schema.

## Writes (rows, into core-declared tables)

| Target | What |
|---|---|
| `fact_metric` | ~960k rows @ `tenant_id='public'`, `visibility='public'`, at the conformed grain (school × period × metric × student-group), using **only** ids from core's vocab |
| `dim_school` | the school spine, keyed on **NCES** (`CA-<cds>` fallback; non-school aggregates excluded) |
| `dim_student_group`, `dim_metric`, `dim_period`, `group_crosswalk` | seeded from core's vocab + this module's CA crosswalk (`seed_ca_dims`, idempotent `ON CONFLICT DO NOTHING`) |

**Dimension-shape changes are `core` changes** — this module may add rows, never columns.

## Reads

Raw CDE / data.ca.gov files (local path or `gs://`, via fsspec); core's vocab (`app.vocab`).

## What stays local to this module

`CDE_CATEGORY` (CDE ReportingCategory → conformed group ids, both code schemes) and `PERIODS` —
California's adapters *into* the shared vocabulary. A second state brings its own crosswalk and
reuses the same ids; the adapters never migrate to core.

## Invariants (tested — `public_metrics/tests/`)

- **Missing is never zero.** CDE suppression (`*`, `N/A`, …) and unparseable cells become
  `None` → `value_status`, never `0.0`. This is the root of the platform's data-honesty rule.
- School identity: 14-digit zero-padded CDS → NCES via crosswalk; `CA-<cds>` fallback so no
  facts are lost.
- New metric id ⇒ add to `app/vocab.py` first (additive = safe); new period ⇒ `PERIODS` here.

## Entry points

`python -m public_metrics.seed_ca_dims --data-dir <path|gs://>` once, then any
`python -m public_metrics.load_ca_<fact>` (× 8). Cloud Shell only; `--dry-run` supported.
Connects as `sip_migrator` with `SET app.tenant='public'`.

## Serving surface

None. Downstream reads `fact_metric` / `dim_*` with SQL.
