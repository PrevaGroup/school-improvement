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
| ORM models | `backend/app/models/reference.py` → `PlanExtraction`; `backend/app/models/tenant.py` → `Plan`, `PlanGoal`, `PlanAction` | **buried in core models; should move here** |
| Docs | `backend/etl/ca/sip/README.md` | |

## Contract

- **Owns:** `plan_extraction` (public — SPSAs are published), `plan_*` (RLS-enforced, tenant-private).
- **Reads:** `dim_school` from `core`; PDF inputs.
- **Serves:** `/plans/*`.
- **Downstream:** the **plan_marts** module reads `plan_extraction`. That table's shape is the
  contract between them.

## Boundary

Depends only on `core`. The RLS-enforced `plan_*` tables are the security-sensitive part — changes
there must preserve tenant isolation (see `core` security model).
