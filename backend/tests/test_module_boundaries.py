"""Enforce the one rule: a module imports `core` or itself, never another module.

CLAUDE.md states the rule; nothing enforced it, so it could only ever be as true as the
last person's care. This walks the AST of every backend source file and fails on the
first import that crosses a module boundary.

## The module map, and why it looks like this

The seam between modules is a DATABASE TABLE (a produced table is the contract), not a
Python import. That is what makes a module swappable: rewrite it however you like, keep
the table shape, and nothing downstream notices.

Producer modules own tables and their own ingest endpoints. Read-serving is ONE module
that reads those tables via SQL and imports none of them:

    core            the frozen contract (config, db, security, star schema, tenancy, vocab)
    public_metrics  public_metrics/        -> fact_metric + the dim_* rows  (relocated)
    sip             etl/ca/sip/, plans.py  -> plan_extraction, plan_* (+ POST /plans/*)
    likeschools     likeschools/           -> mart_school_peer, feat_match_vector,
                                              model_partition_stats  (relocated)
    serving         marts.py, chat.py      -> owns no tables; reads them via raw SQL

`etl/ca/` now holds only `sip/` — public_metrics moved out from under it, and sip keeps that
path until it relocates too. `etl/ca/__init__.py` therefore stays: it's the package marker for
`etl.ca.sip`, nothing more.

`likeschools` is the matching ENGINE only — it has no serving surface. That is a
deliberate call (2026-07-15): `fetch_peer_benchmark` is needed by both the attendance
diagnostic and the school-detail panel, so leaving peer serving inside `likeschools`
would have forced either a cross-module import (breaking the rule) or a duplicate copy
of the percentile/cohort logic (worse). Consolidating all read-serving into one module
keeps the rule intact with the table as the only seam. The cost is that `likeschools`
is not a vertical slice; docs/MODULES.md records this.

`app/main.py` is the composition root — wiring, not a module. It is *expected* to import
every module's router, so it is exempt. It must stay thin: if logic lands in main.py, it
has escaped the rule via this exemption.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent

CORE = "core"
COMPOSITION_ROOT = "app/main.py"

# Dotted-prefix -> owning module. Longest prefix wins, so `etl.ca.sip` beats `etl.ca`.
MODULE_OF_PREFIX: dict[str, str] = {
    "app.config": CORE,
    "app.db": CORE,
    "app.security": CORE,
    "app.models": CORE,
    "app.vocab": CORE,
    "app.usage": CORE,   # spend cap — core operational (serving writes THROUGH core, owns nothing)
    "app.auth_proxy": CORE,  # /__/* reverse proxy — sign-in infrastructure, kin to security.py
    "app.main": "_composition_root",
    "app.plans": "sip",
    "app.plan_loader": "sip",
    "etl.ca.sip": "sip",
    "app.marts": "serving",
    "app.chat": "serving",
    "app.evals_view": "serving",  # read-only admin view over the evals `trace` table (SQL, no import)
    "app.traces": "serving",  # trace EMISSION (GCS, no tables) — eval-trace-system.md phase 1
    "likeschools": "likeschools",
    "public_metrics": "public_metrics",
    "evals": "evals",  # trace store + eval loop (owns 5 tables) — eval-trace-system.md phase 2
    "scoring": "scoring",  # the writing subsystem's record (artifact, score_event) — expansion plan §6
    "roster": "roster",  # sections, enrolments, the section-scoped access edge — expansion plan §7
    "measurement": "measurement",  # estimation frames — engine, no serving surface (expansion plan §10)
    "pooling": "pooling",  # the ONLY module that crosses the district threshold — expansion plan §7
    "registry": "registry",  # nodes, tasks, scoring sites, scoring configuration + the linter
    "corpus": "corpus",  # anchor papers — public reference content, bulk ETL like public_metrics
    "intake": "intake",  # folder -> manifest; roster reconciliation as one assignment
}

# Scanned trees. `tests/`, `scripts/`, and `migrations/` are tooling that legitimately
# reaches across everything (a test imports what it tests), so they are not modules.
#
# ADD A MODULE'S FOLDER HERE WHEN ITS CODE RELOCATES under backend/<X>/. A tree that isn't
# listed is never walked, so its imports are never checked — the module goes dark exactly
# the way `tests/` did when pytest.ini's `testpaths` omitted it, and just as silently.
# `test_the_module_map_covers_every_source_file` only guards files inside these trees, so
# it cannot catch a whole tree being missing. This tuple is the thing to keep honest.
# Kept honest by `test_every_module_tree_is_scanned` and `test_every_package_on_disk_is_scanned`
# below, added 2026-09-05 after the seven writing-subsystem modules sat here UNSCANNED for
# thirteen commits: they were in MODULE_OF_PREFIX, so the map looked complete, but their folders
# were not in this tuple, so no file in any of them was ever walked. The comment above said
# exactly what to do and it still did not happen — which is the argument for a test rather than
# a comment. Third instance of this shape, after pytest.ini `testpaths` and alembic
# `version_locations`: a path missing from a registry is an absence, and absences report green.
SOURCE_TREES = ("app", "etl", "likeschools", "public_metrics", "evals",
                "scoring", "roster", "measurement", "pooling", "registry", "corpus", "intake")

# Package directories that are tooling rather than modules. `tests` and `scripts` reach across
# everything by design; `migrations` is the repo-level alembic tree.
EXEMPT_TREES = frozenset({"tests", "scripts", "migrations"})

# --------------------------------------------------------------------------- #
# Known debt: cross-module imports that exist TODAY, enumerated so the rule can be
# enforced everywhere else. This list may only shrink — and it is now EMPTY.
#
# It held four: `sip` reaching into `public_metrics` for `_engine` and the conformed
# vocab (`METRICS` / `STUDENT_GROUPS`). Cleared 2026-07-15 — the vocab moved to `core`
# (`app/vocab.py`), where a contract two modules must agree on belongs, and sip got its
# own engine factory (`etl/ca/sip/_db.py`). There are no cross-module imports left.
#
# Adding an entry here is NOT how you land a violation. An entry means the module split
# is wrong, which is a design question to raise (CLAUDE.md) — not a line to append.
# --------------------------------------------------------------------------- #
KNOWN_VIOLATIONS: dict[str, set[str]] = {}


def _module_of(dotted: str) -> str | None:
    """Owning module for a dotted import path, or None if it isn't ours (stdlib/3rd-party)."""
    best: str | None = None
    best_len = -1
    for prefix, module in MODULE_OF_PREFIX.items():
        # Guard the boundary so `app.plans_extra` can't match the `app.plans` prefix.
        if (dotted == prefix or dotted.startswith(prefix + ".")) and len(prefix) > best_len:
            best, best_len = module, len(prefix)
    return best


def _dotted_name_of(path: pathlib.Path) -> str:
    rel = path.relative_to(BACKEND).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports_of(path: pathlib.Path) -> list[tuple[str, int]]:
    """Every dotted module this file imports, with line numbers. Relative imports resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _dotted_name_of(path).rsplit(".", 1)[0] if "." in _dotted_name_of(path) else ""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # `from .marts import x` -> resolve against this file's package
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                target = ".".join(filter(None, [".".join(base), node.module or ""]))
            else:
                target = node.module or ""
            if target:
                out.append((target, node.lineno))
    return out


def _source_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for tree in SOURCE_TREES:
        files.extend(
            p for p in (BACKEND / tree).rglob("*.py")
            if "__pycache__" not in p.parts and "tests" not in p.parts
        )
    return sorted(files)


def test_every_module_tree_is_scanned():
    """Every module named in the map must have its folder in SOURCE_TREES.

    `test_the_module_map_covers_every_source_file` cannot catch this: it only looks at files
    inside trees that are already scanned, so a whole missing tree is invisible to it. This is
    the check that would have caught seven dark modules.
    """
    declared = {prefix.split(".")[0] for prefix in MODULE_OF_PREFIX}
    missing = sorted(declared - set(SOURCE_TREES))
    assert not missing, (
        f"modules are in MODULE_OF_PREFIX but their trees are not walked: {missing}. "
        "Their imports are never checked — the boundary rule is unenforced for them.")


def test_every_package_on_disk_is_scanned():
    """The mirror: a new module folder that nobody remembered to declare at all.

    Derived from disk rather than from the map, so a module can only escape the rule by being
    added to EXEMPT_TREES — a visible decision — instead of by omission.
    """
    packages = {p.name for p in BACKEND.iterdir()
                if p.is_dir() and (p / "__init__.py").exists()}
    unscanned = sorted(packages - set(SOURCE_TREES) - EXEMPT_TREES)
    assert not unscanned, (
        f"python packages under backend/ that no tree scans: {unscanned}. "
        "Add them to SOURCE_TREES (and MODULE_OF_PREFIX), or to EXEMPT_TREES if they are "
        "tooling rather than modules.")


def test_the_module_map_covers_every_source_file():
    """A file no prefix claims would be silently exempt — the map must stay exhaustive."""
    unclaimed = [
        str(p.relative_to(BACKEND)) for p in _source_files()
        if _module_of(_dotted_name_of(p)) is None and p.name != "__init__.py"
    ]
    assert not unclaimed, (
        f"These files belong to no module, so nothing checks their imports: {unclaimed}. "
        "Add them to MODULE_OF_PREFIX (and to docs/MODULES.md)."
    )


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: str(p.relative_to(BACKEND)))
def test_module_imports_only_core_or_itself(path: pathlib.Path):
    rel = path.relative_to(BACKEND).as_posix()
    if rel == COMPOSITION_ROOT:
        pytest.skip("composition root: wiring, exempt by design (see module docstring)")

    owner = _module_of(_dotted_name_of(path))
    if owner is None:
        pytest.skip("not owned by a module (namespace __init__)")

    allowed = KNOWN_VIOLATIONS.get(rel, set())
    violations = [
        f"{rel}:{lineno} imports `{dotted}` ({target} module)"
        for dotted, lineno in _imports_of(path)
        if (target := _module_of(dotted)) is not None
        and target not in (CORE, owner)
        and target != "_composition_root"
        and dotted not in allowed
    ]
    assert not violations, (
        f"`{rel}` belongs to the `{owner}` module and may import only `core` or `{owner}`:\n  "
        + "\n  ".join(violations)
        + "\n\nModules integrate through TABLES, not imports — read the other module's "
          "produced table with SQL instead. If that seems impossible, the module split is "
          "wrong; raise it rather than wiring around it (CLAUDE.md)."
    )


def test_no_stale_entries_in_the_known_violations_list():
    """An allow-list that outlives its violations quietly re-legalises them.

    If a listed import is gone, the entry must go too — otherwise the exemption sits there
    ready to permit a future re-introduction of the same cross-module import.
    """
    stale: list[str] = []
    for rel, allowed in KNOWN_VIOLATIONS.items():
        path = BACKEND / rel
        if not path.exists():
            stale.append(f"{rel} (file no longer exists)")
            continue
        actual = {dotted for dotted, _ in _imports_of(path)}
        for gone in allowed - actual:
            stale.append(f"{rel} no longer imports `{gone}`")
    assert not stale, (
        "KNOWN_VIOLATIONS is out of date — these are fixed and must be removed from the "
        f"list: {stale}"
    )
