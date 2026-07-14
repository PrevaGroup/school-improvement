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
| Conformed vocabulary | `backend/etl/ca/_shared.py` (student groups, metric ids) | the shared "yardsticks" |
| Migrations spine | `backend/migrations/versions/0001_initial_schema.py`, `0002_nces_rekey.py` | single linear Alembic history; ordering matters |
| Bootstrap / RLS tests | `backend/sql/00_bootstrap.sql`, `10_rls_smoketest.sql`, `20_reset_database.sql` | roles, RLS smoketest, reset |

## What is NOT core

Module-owned tables that currently sit in `reference.py`/`tenant.py` but belong to a feature:
- `feat_match_vector`, `mart_school_peer`, `model_partition_stats` → **likeschools**
- `plan_extraction`, `plan_*` → **sip**

Pulling those out of `reference.py` into their owning modules is an early reorg step — it's what
lets a module be swapped without editing the shared contract.

## Rule for modules

A module may **read** anything documented here. A module may **not** change it. If a task appears
to need a `core` change (new shared dimension, new conformed metric, schema alteration), stop and
raise it as its own reviewed change — that's the definition of a breaking migration.
