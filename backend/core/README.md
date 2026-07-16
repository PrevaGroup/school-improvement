# core — the frozen contract (scaffold)

> **SCAFFOLD / MAP ONLY — no code has moved here yet.** This folder documents the shared contract
> that every module depends on and where it currently lives. Relocating code here is a later,
> deliberately-reviewed step (see `docs/MODULES.md`). Until then, import from the paths below.

`core` is the one part of the system that is **not swappable**. It's the shared spine — the star
schema, tenancy/RLS, and platform plumbing. Every feature module reads it. **Changing anything
here is a breaking migration** and can ripple into every module, so changes are made deliberately
and reviewed on their own, never folded into a feature change.

## What's in the contract (and where it lives today)

| Piece | Current location | Notes |
|---|---|---|
| Star schema — shared dims + facts | `backend/app/models/reference.py`, `backend/app/models/tenant.py` | `dim_school`, `dim_metric`, `fact_metric`, `dim_period`, etc. |
| Tenancy + RLS | `backend/app/models/reference.py` (`dim_tenant`, `tenant_scope`, `tenant_membership`), `backend/app/security.py`, `backend/app/db.py` | the trust boundary |
| Config / secrets | `backend/app/config.py` | Settings + Secret Manager |
| Conformed vocabulary | `backend/app/vocab.py` (`STUDENT_GROUPS`, `METRICS`, + `*_IDS`) | the shared "yardsticks" — moved out of public_metrics' `_shared.py` 2026-07-15 |
| Migrations spine | `backend/migrations/versions/0001_initial_schema.py`, `0002_nces_rekey.py` | single linear Alembic history; ordering matters |
| Bootstrap / RLS tests | `backend/sql/00_bootstrap.sql`, `10_rls_smoketest.sql`, `20_reset_database.sql` | roles, RLS smoketest, reset |

## What is NOT core

**Module-owned tables — moved out 2026-07-15, and they must stay out:**
- `feat_match_vector`, `mart_school_peer`, `model_partition_stats` → **likeschools**
  (`backend/likeschools/models.py`)
- `plan_extraction`, `plan`, `plan_goal`, `plan_action` → **sip** (`backend/etl/ca/sip/models.py`)

`core` declaring a module's table made every feature change a breaking change to the contract.
`app/models/__init__.py` must **never** re-export them: that would make `core` import a module and
invert the dependency this whole structure rests on. Registration lives in `migrations/env.py`,
`0001_initial_schema.py`, and `scripts/gen_schema_reference.py` — all tooling, which may know
every module. Guarded by `backend/tests/test_schema_inventory.py`.

**Also not core:** California's mapping *into* the vocabulary (`CDE_CATEGORY`, `PERIODS` in
`public_metrics/_shared.py`) belongs to **public_metrics**. The yardstick is shared; the per-state adapter
isn't. And `_engine` factories are module-local — one call on `core`'s `settings`, not shared logic.

## Rule for modules

A module may **read** anything documented here. A module may **not** change it. If a task appears
to need a `core` change (new shared dimension, new conformed metric, schema alteration), stop and
raise it as its own reviewed change — that's the definition of a breaking migration.
