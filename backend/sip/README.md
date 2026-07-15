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

Should depend only on `core`. **It doesn't yet** — four files here import `etl/ca/_shared.py`,
which belongs to **public_metrics**, for `_engine` and the conformed vocab (`METRICS`,
`STUDENT_GROUPS`):

    etl/ca/sip/batch_extract.py · batch_load.py · extract_sip.py · load_plan_extractions.py

That's a real cross-module import — the only one left in the repo. Both `_engine` and the vocab
belong in `core` (`docs/MODULES.md` has said so since the registry was written); moving them is a
`core` change, so it's queued as its own reviewed piece of work rather than folded in sideways.
Until then the four are enumerated in `KNOWN_VIOLATIONS` in
`backend/tests/test_module_boundaries.py`, which enforces the rule everywhere else. **Don't add a
fifth** — the list may only shrink. Note `extract_sip.py` has a second, function-level `_engine`
import (~line 188) that a top-of-file grep misses.

The RLS-enforced `plan_*` tables are the security-sensitive part — changes there must preserve
tenant isolation (see `core` security model). `TenantMixin` comes from `core` and must keep coming
from `core`: a module inventing its own tenancy columns is how the trust boundary quietly breaks.
