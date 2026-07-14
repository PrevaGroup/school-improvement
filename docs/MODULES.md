# Module Registry

The map of the codebase by **feature module** (vertical slice), not by technical layer. This is
the source of truth for "where does feature X live" and for the in-progress reorg. See
`ARCHITECTURE.md` for the logical data model and `CLAUDE.md` for the rules of working here.

## The shape

```
core                      the frozen contract — everything depends on it, changes are breaking
  ├─ star schema          dim_*, fact_metric (models/)
  ├─ tenancy + RLS        dim_tenant, tenant_scope, security.py, db.py
  ├─ conformed vocab      student groups, metric registry
  └─ migrations spine     the single Alembic history (ordering matters)

backend/modules/<X>       swappable feature slices — depend ONLY on core, never on each other
  each owns: README.md · CLAUDE.md · its code · the DB tables it writes · tests
  modules integrate through TABLES (a produced table is the contract), not imports
```

Your "modules replaceable without impacting downstream" goal holds at the **table seam**: a
module can be rewritten freely as long as it still produces its owned tables with the same shape.
The star schema itself is the one thing that is *not* swappable (a schema change is a breaking
migration) — which is why it lives in `core`, not in a module.

## Registry

| Module | Owns (writes) | Reads (from core / public) | Serving surface | Status |
|---|---|---|---|---|
| **public_metrics** | `fact_metric` @ public | CDE/CA raw files → core dims | (bulk ETL, no API) | scattered |
| **sip** (plan extraction) | `plan_extraction`, `plan_*` | PDFs, `dim_school` | `/plans/*` | scattered |
| **likeschools** | `feat_match_vector`, `mart_school_peer`, `model_partition_stats` | `dim_school` (inputs only, never outcomes) | `/like-schools`, `/peer-benchmark` | **worked example** |
| **plan_marts** | (endpoint-composed, no tables yet) | `plan_extraction`, `fact_metric`, `mart_school_peer` | `/marts/*` | scattered |
| **chat** | — | wraps plan_marts + likeschools serving | `/chat` | scattered |

"Scattered" = the feature's code is still spread across the old `app/` + `etl/` + `migrations/`
layout. See each module's README for its component map, and the reorg checklist below.

## Target physical layout

```
backend/
  core/                     ← was app/{config,db,security}.py, app/models/{base,reference,tenant}.py
    config.py  db.py  security.py
    models/                   ONLY shared tables: star dims, fact_metric, tenancy
    vocab/                    conformed vocab (was etl/ca/_shared.py constants)
    migrations/               the Alembic spine
    sql/                      bootstrap roles, RLS smoketest, reset
    CONTRACT.md               the tables + vocab modules are allowed to depend on
  app/
    main.py                 ← thin composition root: mount each module's router
  modules/
    public_metrics/         ← was etl/ca/*.py, _shared.py, seed_ca_dims.py
    sip/                    ← was etl/ca/sip/*, app/plans.py, app/plan_loader.py, migration 0003
    likeschools/            ← was likeschools/*.md, etl/peers/*, the 3 mart models, migration 0004
    plan_marts/             ← was app/marts.py
    chat/                   ← was app/chat.py
frontend/                   ← React + Vite (not yet built)
```

Note: Python package dirs use underscores (`public_metrics`), because hyphens aren't importable.

## Migrations policy

One linear Alembic history stays in `core/migrations/` (the schema spine — ordering matters). But
each table-owning module **owns its migration files**, registered into the shared history via
Alembic `version_locations`, and lists them in its `CONTRACT.md`. This gives module ownership
without the branch-merge pain of independent migration chains. Promote a module to an Alembic
branch label later only if it genuinely needs an independent deploy cadence.

## Reorg checklist (per module)

- [ ] `README.md` — component map + how-to-change runbook, reconciled to the code
- [ ] `CLAUDE.md` — module scope + guardrails
- [ ] `CONTRACT.md` — tables owned, tables/vocab read from core, migration revisions
- [ ] code moved under `backend/modules/<X>/`, imports updated
- [ ] owned migration file(s) relocated + wired via `version_locations`
- [ ] tests (at minimum a characterization test of current behavior)
- [ ] boundary test passes (no import into another module)

## Status

- [x] `CLAUDE.md` (repo rules) + this registry
- [x] `likeschools` — README component map + module CLAUDE.md (docs; code not yet relocated)
- [ ] `core/` carve-out
- [ ] `likeschools` code relocation (decouple the 3 mart models from `core` `reference.py` first)
- [ ] remaining modules
- [ ] cross-module boundary test
