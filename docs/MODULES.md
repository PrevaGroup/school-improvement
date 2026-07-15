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

backend/<X>               swappable modules, one folder each — depend ONLY on core, never each other
  producers                likeschools · sip · public_metrics — each owns the tables it writes
  serving                  owns no tables; reads the producers' tables with SQL
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
| **likeschools** (engine) | `feat_match_vector`, `mart_school_peer`, `model_partition_stats` | `dim_school` (inputs only, never outcomes) | **none — engine only** | **relocated** |
| **serving** | — (owns no tables) | `plan_extraction`, `fact_metric`, `mart_school_peer`, `dim_*` — all via SQL | `/marts/*`, `/chat` | scattered |

"Scattered" = the feature's code is still spread across the old `app/` + `etl/` + `migrations/`
layout. **"Relocated"** = it lives under `backend/<X>/`, migration included. See each module's
README for its component map, and the reorg checklist below.

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
  *ingest* endpoints. `likeschools` is the matching **engine** — `backend/likeschools/` and the
  three tables it writes, nothing more.
- **`serving`** owns no tables. It reads every producer's tables with SQL and imports none of
  them, so the table stays the only seam.

This keeps the one rule **unchanged** and swappability intact where it was always the point:
rewrite the matching engine however you like, keep `mart_school_peer`'s shape, and serving
never notices. The cost is that `likeschools` is not a vertical slice, and the peer endpoints
live in `serving` — accepted deliberately over weakening the rule to allow module-to-module
imports.

`backend/tests/test_module_boundaries.py` enforces this map in CI.

> **Known future pressure on "serving owns no tables":** the planned `chat.py` overhaul retains
> **traces** to fuel an eval system — and a trace table would make `serving` a **producer**,
> contradicting the invariant above. The overhaul is parked, but the storage call should be made
> **before the first trace is written**, not after. Options and a recommendation:
> [`docs/design/chat-traces-and-evals.md`](design/chat-traces-and-evals.md).

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
  likeschools/              ← DONE 2026-07-15: build_peers.py, models.py, migrations/0004_*
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
      `backend/sip/`, `backend/public_metrics/`, `backend/serving/`
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

**What the boundary test found, and what happened to it:** four files in `sip` reaching into
`public_metrics` for `_engine` and the conformed vocab (`METRICS`, `STUDENT_GROUPS`) — relative
imports (`from .._shared import ...`) that a line-start grep had missed. All four are now fixed
(see the vocab carve-out below). **`KNOWN_VIOLATIONS` is empty: there are no cross-module imports
left in the repo,** and the rule is enforced with no exemptions.

**Core carve-out — module tables (done 2026-07-15):**
- [x] `core` no longer declares a single module-owned table. Models moved to the module that
      writes them: `likeschools/models.py` (its 3 mart tables) and `etl/ca/sip/models.py`
      (sip's `plan_extraction` + `plan` / `plan_goal` / `plan_action`). `from app.models import
      Base` now sees **14** tables — all genuinely shared. Changing a module's table is no
      longer a change to the frozen contract.
- [x] Registration handled where it belongs. A model only reaches `Base.metadata` if something
      imports it, and **two** places need the full metadata: `migrations/env.py` (autogenerate —
      a table it can't see becomes DROP TABLE) and `0001_initial_schema.py` (`create_all` on a
      fresh DB). Both now import the module models explicitly. `app/models/__init__.py` does
      **not** re-export them — that would make `core` import a module and invert the dependency.
- [x] Models sat beside their module's existing code at the time (`etl/peers/`, `etl/ca/sip/`)
      rather than in the docs-only module folders — splitting one module across two directories
      is worse than the problem. `likeschools` has since relocated wholesale (below); `sip` still
      waits, so its models remain at `etl/ca/sip/models.py` alongside the rest of it.

**Fixed on the way (latent, would only bite a from-scratch build):** `0001` created its tables
with an unbounded `Base.metadata.create_all()`, i.e. every table the live models declared —
including `plan_extraction` and the three peer tables that `0003` / `0004` then `create_table`
again. So `alembic upgrade head` on an empty database failed at `0003` with DuplicateTable —
exactly the path `sql/20_reset_database.sql` exists to exercise. `0001` is now bounded to its own
baseline (`REFERENCE_TABLES` + `PRIVATE_TABLES`), and a test renders its DDL through a mock
engine to keep it that way.

**Core carve-out — vocab (done 2026-07-15):**
- [x] `STUDENT_GROUPS` + `METRICS` → `core` (`app/vocab.py`). Both public_metrics (which seeds the
      dims from them) and sip (which pins the extractor's prompt to them, so a plan measure maps
      onto a real `dim_metric.metric_id` instead of writing rows that join to nothing) need them.
      A vocabulary two modules must agree on can't live inside one of them. `_shared.py`
      re-exports them so the CA loaders read unchanged.
- [x] **`CDE_CATEGORY` and `PERIODS` deliberately stay in public_metrics.** They're California's
      mapping *into* the vocabulary, not the vocabulary — a second state brings its own crosswalk
      and reuses these ids unchanged. That line is what "conformed" means: shared yardstick,
      per-state adapters.
- [x] `_engine` → sip's own `etl/ca/sip/_db.py`, not `core`. It isn't shared logic, just one call
      on `core`'s `settings.migration_database_url`. The obvious core home (`app/db.py`) builds the
      *app's* engine at import time as `sip_app`, so importing it from ETL would demand the app
      password and drag FastAPI in. A module opening its own connection is also more honest —
      sharing an engine factory is coupling, not reuse.
- [x] `scripts/gen_schema_reference.py` had the same metadata bug as `env.py` (it builds from
      `app.models`, so post-carve it would have silently emitted a 14-table reference). Fixed and
      regenerated: **SCHEMA_REFERENCE.md now documents all 21 tables** — it had been stale since
      0003, never listing `plan_extraction` or the peer tables.

**Docs reconciled to the decision (done 2026-07-15):**
- [x] `plan_marts/` + `chat/` scaffolds folded into `backend/serving/` and deleted
- [x] `ARCHITECTURE.md` §4 "Modules" — states the *idea* (the seam, why producer/consumer, that
      it's enforced) and defers the inventory here. Its old path-by-path "Repository index" was
      **deleted, not updated**: it was a second map of the same codebase, grouped by technical
      layer, and it had silently stopped mentioning `etl/peers/`, `app/marts.py`, `app/chat.py`,
      and `backend/tests/`. Two maps drift; this file is the one that's reconciled to the code.
- [x] `likeschools/CLAUDE.md` — was still granting itself scope over `app/marts.py` + `app/chat.py`
      (the pre-decision design). That's an auto-loaded instruction file, so it was actively
      steering work into a rule violation. Now engine-only.
- [x] `sip/README.md` — claimed "depends only on `core`", which is false; now names the four
      `_shared` imports and points at `KNOWN_VIOLATIONS`.

**Code relocation — `likeschools` done 2026-07-15 (the worked example):**
- [x] `etl/peers/*` → `backend/likeschools/`; `etl/peers/` is gone. Runbook changed:
      **`python -m likeschools.build_peers`** (was `python -m etl.peers.build_peers`).
- [x] **`version_locations` proven.** `0004_peer_tables.py` → `likeschools/migrations/`, wired in
      `alembic.ini`. Still ONE linear history — `alembic history` reports `0003 -> 0004 (head)`,
      unchanged, and it runs offline so it's cheap to re-check. Alembic stitches by
      `down_revision`; the folder has no bearing on order. A revision outside a listed path is
      invisible to Alembic — a migration that silently never runs.
- [x] Caught in the move: `build_peers.py` did `sys.path.append(parents[2])` to reach `backend/`.
      From `etl/peers/` that was right; from `likeschools/` it lands on the **repo root**. Only
      breaks when run as a script in Cloud Shell — tests never see it, because `conftest.py`
      already puts `backend/` on `sys.path`. **Check `parents[N]` on every file that moves depth.**
- [x] `SOURCE_TREES` in `tests/test_module_boundaries.py` now lists `likeschools`. An unlisted
      tree is never walked, so the module would go dark to the boundary check — the same silent
      failure as `pytest.ini`'s `testpaths` omitting `tests/`.

**Code relocation — remaining (NOT started):**
- [ ] `public_metrics` (`etl/ca/*.py`) — doesn't touch `main.py`. Changes every loader runbook
      command (`python -m etl.ca.load_ca_*` → `python -m public_metrics.load_ca_*`).
- [ ] `sip`, `serving`, `core` — **each changes `app/main.py`'s imports**, which collides with
      go-live task 3.1c (`/api/*` prefix), also on `main.py` + the route contract. Sequence
      deliberately; don't run both at once.
- [ ] **While `db.py` moves to `core/`: make the engine lazy.** A function or cached factory —
      **no module-level `create_engine`**. Today `app/db.py` runs `engine = _build_engine()` at
      **import time**, so importing *any* `app` module requires DB credentials **and** an
      installed `psycopg` driver (`create_engine` is lazy about *connecting*, not about
      importing the DBAPI). That is the only reason `backend/conftest.py` has to inject a fake
      password to collect the suite. Cheapest available win for testability, and the code is
      moving to `core` regardless — so it costs one extra diff, not a separate project. Trim
      the conftest workaround in the same change, so it can't outlive its cause.
- [ ] **AFTER the relocation, never during: unify the two `plan_status` vocabularies.**
      `fetch_school_plan` emits `on_file`/`not_on_file`; chat's attendance tool computes
      `has_attendance_plan`/`no_attendance_section`/`not_on_file` — same field name, two
      vocabularies, both feeding the model. Normalizing it *during* a move would be a behavior
      change hiding inside a relocation, which is precisely what the characterization net
      exists to catch. When it happens,
      `tests/test_chat_tools.py::test_query_school_plan_status_vocabulary_differs_from_attendance_tool`
      flips from *documenting an inconsistency* to *enforcing a contract*, in that same diff.
