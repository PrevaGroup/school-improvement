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
| **sip** (plan extraction) | `plan_extraction`, `plan_*` | PDFs, `dim_school` | `/plans/*` (ingest) | scattered |
| **likeschools** (engine) | `feat_match_vector`, `mart_school_peer`, `model_partition_stats` | `dim_school` (inputs only, never outcomes) | **none — engine only** | scattered |
| **serving** | — (owns no tables) | `plan_extraction`, `fact_metric`, `mart_school_peer`, `dim_*` — all via SQL | `/marts/*`, `/chat` | scattered |

"Scattered" = the feature's code is still spread across the old `app/` + `etl/` + `migrations/`
layout. See each module's README for its component map, and the reorg checklist below.

`app/main.py` is the **composition root**, not a module: it mounts every module's router and
is the one file allowed to import across modules. It must stay thin — logic that lands there
has escaped the rule through that exemption.

### Producers own tables; serving is one module (decided 2026-07-15)

The earlier shape gave `likeschools` its own serving surface (`/like-schools`,
`/peer-benchmark`) and made `chat` a module that wrapped `plan_marts` + `likeschools`. That
does not survive contact with the code: `fetch_peer_benchmark` is needed by **both** the
attendance diagnostic and the school-detail panel, so peer serving inside `likeschools` forces
either a cross-module import (breaks the one rule) or a second copy of the percentile/cohort
logic (worse than the import). `chat` had the same problem — it imports four `marts` functions.

So the split is **by producer/consumer, not by feature**:

- **Producer modules** (`public_metrics`, `sip`, `likeschools`) own tables and their own
  *ingest* endpoints. `likeschools` is the matching **engine** — `etl/peers` and the three
  tables it writes, nothing more.
- **`serving`** owns no tables. It reads every producer's tables with SQL and imports none of
  them, so the table stays the only seam.

This keeps the one rule **unchanged** and swappability intact where it was always the point:
rewrite the matching engine however you like, keep `mart_school_peer`'s shape, and serving
never notices. The cost is that `likeschools` is not a vertical slice, and the peer endpoints
live in `serving` — accepted deliberately over weakening the rule to allow module-to-module
imports.

`backend/tests/test_module_boundaries.py` enforces this map in CI.

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
                              ENGINE ONLY — no serving surface
  sip/                      ← was etl/ca/sip/*, app/plans.py, app/plan_loader.py, migration 0003
  public_metrics/           ← was etl/ca/*.py, _shared.py, seed_ca_dims.py
  serving/                  ← was app/marts.py + app/chat.py (was: separate plan_marts + chat
                              modules; merged 2026-07-15 — see the decision above)
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
      — NB: `plan_marts/` + `chat/` are pre-decision scaffolds and now name modules that no
      longer exist; they fold into `serving/` when the code relocates (docs-only, not yet done)
- [x] `likeschools` — full README component map + module `CLAUDE.md`
- [x] Reconciled the drifted design docs (status banners → code is source of truth)

**Test safety net + enforcement (done 2026-07-15):**
- [x] CI — GitHub Actions runs the suite on every PR (`.github/workflows/ci.yml`). There was
      none before, and the suite it would have run was collecting **zero tests**: `testpaths`
      excluded `tests/`, `test_marts.py` couldn't import without DB credentials, and the sip
      tests `importorskip`-ed themselves into a silent green. Now 56 pass.
- [x] HTTP route contract frozen (`tests/test_route_contract.py`) — all 13 published paths, so
      a module move can't rename a URL out from under the frontend.
- [x] Cross-module boundary test (`tests/test_module_boundaries.py`) — AST-walks every import
      and fails on the first that crosses a module line.

**What the boundary test found:** the module map above is otherwise clean *today* — the only
import violations are four files in `sip` reaching into `public_metrics` for `_engine` and the
conformed vocab (`METRICS`, `STUDENT_GROUPS`). Both belong in `core` (this doc already said so).
They're enumerated in `KNOWN_VIOLATIONS` so the rule can be enforced everywhere else; the list
may only shrink, and a staleness test stops it becoming fiction.

**Code relocation (NOT started):**
- [ ] `core/` carve-out — the real remaining problem. `core` currently *owns module tables*:
      `app/models/reference.py` holds likeschools' `feat_match_vector` / `mart_school_peer` /
      `model_partition_stats` and sip's `PlanExtraction`; `tenant.py` holds sip's `Plan` /
      `PlanGoal` / `PlanAction`. So "core is frozen" isn't true yet — every module change is a
      core change. This also clears the four `KNOWN_VIOLATIONS` (vocab + `_engine` → core).
      **Risk to respect:** `migrations/env.py` builds `Base.metadata` from `app.models`; if
      models move without env.py importing them, autogenerate will emit DROP TABLE.
- [ ] `likeschools` code relocation (first safe step: decouple the 3 mart models from `core`
      `reference.py` — grep-confirmed only `build_peers.py` imports them)
- [ ] remaining modules
