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

backend/<X>               swappable feature slices, one folder each (likeschools, sip,
                          public_metrics, plan_marts, chat) — depend ONLY on core, never each other
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

Feature modules sit **directly under `backend/`** (honoring the existing `backend/likeschools/`),
alongside `app/` and `etl/` during the transition — not nested in a new `backend/modules/` layer.

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
  likeschools/              ← + etl/peers/*, the 3 mart models, migration 0004 (docs already here)
  sip/                      ← was etl/ca/sip/*, app/plans.py, app/plan_loader.py, migration 0003
  public_metrics/           ← was etl/ca/*.py, _shared.py, seed_ca_dims.py
  plan_marts/               ← was app/marts.py (plan-content marts only)
  chat/                     ← was app/chat.py
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
- [ ] code moved under `backend/<X>/`, imports updated
- [ ] owned migration file(s) relocated + wired via `version_locations`
- [ ] tests (at minimum a characterization test of current behavior)
- [ ] boundary test passes (no import into another module)

## Status

**Docs & scaffolding (done — no runtime code changed):**
- [x] `CLAUDE.md` (repo rules) + this registry
- [x] Scaffold folders with component-map READMEs: `backend/core/`, `backend/likeschools/`,
      `backend/sip/`, `backend/public_metrics/`, `backend/plan_marts/`, `backend/chat/`
- [x] `likeschools` — full README component map + module `CLAUDE.md`
- [x] Reconciled the drifted design docs (status banners → code is source of truth)

**Code relocation (NOT started — deferred until there's a test safety net and the prototype
milestone is clear):**
- [ ] `core/` carve-out
- [ ] `likeschools` code relocation (first safe step: decouple the 3 mart models from `core`
      `reference.py` — grep-confirmed only `build_peers.py` imports them)
- [ ] remaining modules
- [ ] import smoke-test + cross-module boundary test
