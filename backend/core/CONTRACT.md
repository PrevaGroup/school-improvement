# core — CONTRACT

What every module may depend on, and therefore what cannot change without a reviewed,
breaking migration (CLAUDE.md: never fold a `core` change into a feature change).

## Tables core DECLARES (14 — the star spine + tenancy)

| Table | Notes |
|---|---|
| `dim_school`, `dim_date`, `dim_period`, `dim_metric`, `dim_student_group`, `dim_instrument`, `dim_peer_group`, `dim_metric_relationship`, `group_crosswalk`, `ref_benchmark` | conformed dimensions / reference |
| `fact_metric` | the keystone fact — grain: school × period × metric × student-group. **Rows written by public_metrics**, shape owned here |
| `dim_tenant`, `tenant_scope`, `tenant_membership` | tenancy registry |

Declares ≠ writes: core writes nothing. Producers write rows; core owns the shapes everyone
joins on. Models: `app/models/{reference,tenant}.py`.

## The trust boundary (RLS)

- `PRIVATE_TABLES` = `fact_metric`, `dim_period`, `plan`, `plan_goal`, `plan_action` — RLS
  ENABLE + FORCE + tenant policies. `SCHOOL_SCOPED_TABLES` = `fact_metric`.
  (Names sip's three plan tables by string — the boundary is core's job; a string is not an import.)
- `TenantMixin` (`app/models/tenant.py`) — `tenant_id` + `visibility`. Modules with private
  tables **apply** it; they must never invent their own tenancy columns.
- `security.py` (identity → tenant), `db.py` (`SET LOCAL app.tenant`; `get_db` / `get_db_public`).

## The conformed vocabulary (`app/vocab.py`)

`METRICS`, `STUDENT_GROUPS` (+ `METRIC_IDS`, `STUDENT_GROUP_IDS`). These ids are persisted in
`fact_metric` — **adding is safe; renaming/removing orphans data and needs a migration.**

## Migration revisions owned

`0001_initial_schema` (baseline + RLS — bounded `create_all`; see its comments), `0002_nces_rekey`.
The Alembic spine (`migrations/`) and `alembic.ini`'s `version_locations` list are core's.

## What modules may import

`app.config`, `app.db`, `app.security`, `app.models`, `app.vocab` — nothing else in core, and
never another module. Enforced: `tests/test_module_boundaries.py`.

## Registration rule (the DROP TABLE trap)

A module's models reach `Base.metadata` only if imported by `migrations/env.py`,
`0001_initial_schema.py`, and `scripts/gen_schema_reference.py`. `app/models/__init__.py` must
**never** re-export module models — that inverts the dependency. Guarded:
`tests/test_schema_inventory.py`.
