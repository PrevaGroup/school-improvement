# sip — CONTRACT

Plan ingest: PDF → Claude extraction → reviewable JSON → tables. Owns the plan data in both
tiers, and the ingest endpoints that produce it.

## Tables owned (declares AND writes) — models in `etl/ca/sip/models.py`

| Table | Tier | Notes |
|---|---|---|
| `plan_extraction` | **public** (SPSAs are published documents; no RLS) | the full extracted plan as queryable JSONB (`document`), keyed `plan_id`, joined via `school_id`. **The seam `serving` reads** — its shape (and the `document` JSON produced by `schema.py`'s `ExtractedPlan`) is the contract |
| `plan`, `plan_goal`, `plan_action` | **private** (RLS via core's `TenantMixin`) | normalized stubs, loaded idempotently with deterministic ids (`plan_loader.py`) |

The extraction JSON schema (`etl/ca/sip/schema.py`) is part of the contract: `serving`'s
`attendance_slice` / `full_plan_goals` walk `document["goals"][*]["actions"]` by shape.

## Migration revisions owned

`0003_plan_extraction` — **still in `migrations/versions/`**; moves to `sip/migrations/` +
`version_locations` when the module relocates (likeschools is the pattern).

## Reads

`dim_school` (id resolution), core's vocab (`app.vocab` — the extractor pins its prompt to
`METRIC_IDS` / `STUDENT_GROUP_IDS`, so a plan measure maps onto a real id or proposes null;
an invented id would write rows that join to nothing). PDFs; GCS via fsspec.

## Serving surface (ingest, not read)

`POST /api/plans/extract`, `POST /api/plans/load` — gated on `get_current_tenant`
(private path). Read-serving of plan content belongs to `serving`.

## Module internals worth naming

`_db.py` `_engine()` — sip's own, deliberately duplicated one-liner (a shared engine factory is
coupling, not reuse). `TenantMixin` must keep coming from core — a module inventing its own
tenancy columns is how the trust boundary quietly breaks.

## Invariants

- Depends only on core (was the last `KNOWN_VIOLATIONS` holder; now clean and enforced).
- `plan_extraction` rows are immutable raw-ish artifacts: re-extraction replaces, loaders never
  edit `document` in place.
- Tests: `etl/ca/sip/tests/` (loader shape, per-file resilience of the batch path).
