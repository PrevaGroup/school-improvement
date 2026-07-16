# Working in this repo (read first)

This is a **modular** codebase. The goal: each module is a self-contained slice with its own
tests, so a change stays *contained* — you can work on one module, test it in isolation, and not
make the rest of the app brittle. Modularity comes from the **boundaries and the tests**, not
from process ceremony. Keep the boundaries clean; how you sequence the work is a judgment call.

## The one rule that matters

> **Keep each change inside one module, and depend only on `core` — never import another module.**

A file in a feature module `backend/<X>/` (e.g. `backend/likeschools/`) may import from:
- `core` (the shared contract — star schema, db, security, config, vocab), and
- its own module `backend/<X>/`.

It may **not** import from another module `backend/<Y>/`. Modules talk to each other only through
**database tables** (a produced table is a contract) or through `core`. If you think you need
a cross-module import, stop — that's a design smell; raise it instead of wiring it.

**This is enforced, not aspirational**: `backend/tests/test_module_boundaries.py` walks the AST
of every import and fails CI on the first one that crosses a module line. It carries the module
map and a `KNOWN_VIOLATIONS` list, which as of 2026-07-15 is **empty** — there are no
cross-module imports in the repo and the rule has no exemptions. Adding an entry to that list is
not how you land a violation: an entry means the module split is wrong, which is a design
question to raise, not a line to append.

The rule survives only because of how the modules are cut: **producers** (`public_metrics`,
`sip`, `likeschools`) own tables; **`serving`** owns none and reads them with SQL. Cutting by
feature instead — giving `likeschools` its own peer endpoints — forces a cross-module import,
which is exactly the pressure that would erode the rule. See docs/MODULES.md. `app/main.py` is
the composition root and is the one exempt file; keep it thin.

## `core` is a frozen contract

`core/` holds the star schema (`dim_*`, `fact_metric`), tenancy/RLS, `db.py`, `security.py`,
`config.py`, and the conformed vocabulary. Everything depends on it. **Changing `core` is a
breaking migration** and can ripple into every module. Do not edit `core` casually. If a task
seems to need a `core` change, treat that as its own reviewed piece of work — flag it to the
human, don't fold it silently into a feature change.

## How to work

1. **Use branches when they help — not by rule.** A larger, riskier, or worked-in-parallel change
   earns its own branch + PR; a small, well-contained fix can go straight to `main`. What keeps a
   change safe is the module boundary and the tests, not the branch. If you do branch, keep it to
   one module.
2. **Read the module's own `README.md` and `CLAUDE.md` first** — they say what the module owns
   (which tables), what it reads, and how to change it safely.
3. **The code is the source of truth**, not the spec docs. Where a `docs/` spec and the code
   disagree, the code wins; fix the doc (this repo has a history of spec/code drift).
4. **Run the module's tests** before and after your change. If a module has no tests yet, adding
   a characterization test for what you touched is part of the work.
5. **Don't reach across the tree.** Editing files outside your module (especially `core/` or
   another module) is the thing this structure exists to prevent.

## Running the tests

**The unit tests need no database** — every DB call is patched. CI (`.github/workflows/ci.yml`)
is the source of truth; it installs the real `requirements.txt` and runs the whole suite on
every PR.

To run them locally, use an **isolated venv outside the repo** (a scratch dir). **Do not
pip-install project deps into the system Python.** This is *not* an exception to "ETL runs in
Cloud Shell, never locally" — that rule is about ETL/extractors, which hit Cloud SQL, spend
Anthropic tokens, and need cloud credentials. Pure-logic tests are a different thing.

```
python -m venv <scratch>/tv
<scratch>/tv/Scripts/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cd backend && <scratch>/tv/Scripts/python -m pytest
```

> **Install the full `requirements.txt`, not a hand-picked subset.** A minimal venv silently
> *under-collects*: tests whose imports are missing never run, and the suite still reports
> green. That happened — a hand-picked venv reported 81 passing where CI ran 116. If your local
> count disagrees with CI, believe CI.

`backend/conftest.py` supplies a throwaway DB password so `app/*` imports without credentials —
`app/db.py` builds the engine at **import time**, which otherwise reaches for Secret Manager.
That is a workaround for a smell, not a feature; see `docs/MODULES.md`.

**`testpaths` must list every test directory.** It once read `etl app`, so `tests/` was never
collected and those tests silently never ran. Any module carve-out that adds
`backend/<X>/tests/` **must add that path to `pytest.ini`**, or it goes dark the same way.

## Where things are

- `docs/MODULES.md` — the module registry: every module, what it owns, what it reads, current
  file locations, and reorg status. **Start here to find a feature's components.**
- `docs/GO_LIVE_PLAN.md` — the plan to put this on the internet (Identity Platform sign-in, the `frontend/`
  SPA, the domain). **Read its §2.5 before touching `serving/` or `app/main.py`.**
- `ARCHITECTURE.md` — the logical model (5 data layers, trust boundary, pipelines).
- `backend/core/` — the shared contract (see above).
- `backend/<X>/` — modules, one folder each: the producers `likeschools`, `sip`,
  `public_metrics` (each owns tables) and `serving` (owns none; reads them). They sit
  alongside `app/` and `etl/` until the code they map is relocated.

## Reorg in progress

This repo is mid-migration from a layer-organized layout (`app/`, `etl/`, `migrations/`) to the
module layout above. `docs/MODULES.md` tracks what's moved and what hasn't. `likeschools` is the
worked example. Until a module is fully carved out, its components may still be scattered — the
registry tells you where each piece currently lives.
