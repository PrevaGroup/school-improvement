# sip — School Improvement Plan extraction & load (scaffold)

> **SCAFFOLD / MAP ONLY — no code has moved here yet.** This documents where the feature's code
> currently lives. Relocation is a later step (see `docs/MODULES.md`). Import from the paths below.

Turns published SPSA PDFs into structured, queryable plan data:
`PDF → POST /plans/extract → ExtractedPlan JSON → human review → POST /plans/load → plan_* tables`.
The extractor uses Claude to read the PDF natively.

## Component map (where the code is today)

| Concern | File(s) | Notes |
|---|---|---|
| Extractor | `backend/etl/ca/sip/extract_sip.py`, `schema.py` | Claude reads PDF → `ExtractedPlan` |
| Batch tools | `backend/etl/ca/sip/batch_extract.py`, `batch_load.py`, `load_plan_extractions.py` | |
| Extractor context / examples | `backend/etl/ca/sip/contexts/lbusd_spsa.txt`, `example_extract.json` | |
| Serving API | `backend/app/plans.py` | `/plans/extract`, `/plans/load` |
| Loader | `backend/app/plan_loader.py` | idempotent, deterministic IDs |
| Schema / DDL | `backend/migrations/versions/0003_plan_extraction.py` | creates the plan tables |
| ORM models | `backend/etl/ca/sip/models.py` → `PlanExtraction`, `Plan`, `PlanGoal`, `PlanAction` | moved out of core 2026-07-15; registered via `migrations/env.py` + `0001`. `TenantMixin` still comes from `core` — the trust boundary is core's to define |
| Docs | `backend/etl/ca/sip/README.md` | |

## Contract

- **Owns:** `plan_extraction` (public — SPSAs are published), `plan_*` (RLS-enforced, tenant-private).
- **Reads:** `dim_school` from `core`; PDF inputs.
- **Serves:** `/plans/*`.
- **Downstream:** the **serving** module reads `plan_extraction` (with SQL, never an import).
  That table's shape is the contract between them.

## Boundary

Depends only on `core` — and as of 2026-07-15 that's actually true, enforced by
`backend/tests/test_module_boundaries.py` rather than asserted here.

It wasn't before: four files imported public_metrics' `_shared.py` for `_engine` and
the conformed vocab. The vocab moved to `core` (`app/vocab.py`) — a vocabulary two modules must
agree on can't live inside one of them — and the engine is now this module's own (`_db.py`), a
deliberate one-line near-copy rather than a shared helper, because sharing an engine factory is
coupling, not reuse.

- **Vocab:** import `METRICS` / `STUDENT_GROUPS` (or `METRIC_IDS` / `STUDENT_GROUP_IDS`) from
  `app.vocab`. The extractor pins its prompt to these so a plan measure maps onto a real
  `dim_metric.metric_id`; an id invented here writes rows that join to nothing.
- **Engine:** `from ._db import _engine` — runs as the migrator role.
- **Never** import `public_metrics._shared` or any other module. Read their tables with SQL instead.

The RLS-enforced `plan_*` tables are the security-sensitive part — changes there must preserve
tenant isolation (see `core` security model). `TenantMixin` comes from `core` and must keep coming
from `core`: a module inventing its own tenancy columns is how the trust boundary quietly breaks.
