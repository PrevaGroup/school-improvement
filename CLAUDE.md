# Working in this repo (read first)

This is a **modular** codebase. The point of the module structure is that you can work on
one module in one AI session without colliding with work happening in another module (or on
another machine). To keep that true, follow these rules.

## The one rule that matters

> **Stay inside one module per session, and depend only on `core` — never on another module.**

A file in a feature module `backend/<X>/` (e.g. `backend/likeschools/`) may import from:
- `core` (the shared contract — star schema, db, security, config, vocab), and
- its own module `backend/<X>/`.

It may **not** import from another module `backend/<Y>/`. Modules talk to each other only through
**database tables** (a produced table is a contract) or through `core`. If you think you need
a cross-module import, stop — that's a design smell; raise it instead of wiring it.

## `core` is a frozen contract

`core/` holds the star schema (`dim_*`, `fact_metric`), tenancy/RLS, `db.py`, `security.py`,
`config.py`, and the conformed vocabulary. Everything depends on it. **Changing `core` is a
breaking migration** and can ripple into every module. Do not edit `core` casually. If a task
seems to need a `core` change, treat that as its own reviewed piece of work — flag it to the
human, don't fold it silently into a feature change.

## How to work

1. **Branch per unit of work:** `git switch -c feat/<module>-<short-desc>`. One module per branch.
2. **Read the module's own `README.md` and `CLAUDE.md` first** — they say what the module owns
   (which tables), what it reads, and how to change it safely.
3. **The code is the source of truth**, not the spec docs. Where a `docs/` spec and the code
   disagree, the code wins; fix the doc (this repo has a history of spec/code drift).
4. **Run the module's tests** before and after your change. If a module has no tests yet, adding
   a characterization test for what you touched is part of the work.
5. **Don't reach across the tree.** Editing files outside your module (especially `core/` or
   another module) is the thing this structure exists to prevent.

## Where things are

- `docs/MODULES.md` — the module registry: every module, what it owns, what it reads, current
  file locations, and reorg status. **Start here to find a feature's components.**
- `ARCHITECTURE.md` — the logical model (5 data layers, trust boundary, pipelines).
- `backend/core/` — the shared contract (see above).
- `backend/<X>/` — feature modules, one folder each (e.g. `likeschools`, `sip`, `public_metrics`,
  `plan_marts`, `chat`): self-contained vertical slices, sitting alongside `app/` and `etl/`
  until the code they map is relocated.

## Reorg in progress

This repo is mid-migration from a layer-organized layout (`app/`, `etl/`, `migrations/`) to the
module layout above. `docs/MODULES.md` tracks what's moved and what hasn't. `likeschools` is the
worked example. Until a module is fully carved out, its components may still be scattered — the
registry tells you where each piece currently lives.
