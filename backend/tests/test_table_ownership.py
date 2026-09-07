"""A module writes only the tables it owns. The other half of the boundary rule.

`test_module_boundaries.py` enforces the import half: a module may import only `core` or itself.
It cannot see the half that actually matters, because modules integrate through TABLES — so a
module can obey the import rule perfectly while writing straight into another module's tables with
raw SQL, and nothing anywhere notices.

That is not hypothetical. `scoring/seed_demo.py` was written on 2026-09-05, one commit after the
import scan was fixed, and it INSERTed six `registry_node_version` rows — publishing rubric
versions from the scoring module, bypassing the registry linter that is supposed to gate exactly
that. Every test passed. The import scan was clean, because there was no import.

"A produced table is the contract" only means something if one module produces it. Two writers is
not a contract; it is a shared mutable global with a longer name.

## Scope, stated rather than implied

Ownership is DERIVED, not declared: a module owns the tables its own models give a
`__tablename__`. There is no map here to fall out of date, which is deliberate given that three
registries in this repo have now gone stale silently.

Only the modules listed in OWNED_BY_MODELS participate. Tables outside that set — core's star
schema, the `plan_*` family — are ignored, because their ownership predates this convention and
sorting it out is a separate piece of work rather than something to smuggle into a test. That is a
real limit, and it is written down instead of being left for someone to discover.

Migrations are exempt: a migration creates and seeds the tables its own module owns, and it is
pinned to a revision where the module layout may have been different.
"""
from __future__ import annotations

import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent

# The modules whose table ownership is enforced. Adding a module here is how it opts in.
SCANNED = ("scoring", "roster", "measurement", "pooling", "registry", "corpus", "intake", "evals")

TABLENAME_RE = re.compile(r'__tablename__\s*=\s*["\']([a-z_0-9]+)["\']')
# INSERT INTO x / UPDATE x SET / DELETE FROM x, in a SQL string anywhere in the file.
WRITE_RE = re.compile(
    r"\b(?:INSERT\s+INTO|DELETE\s+FROM)\s+([a-z_0-9]+)|\bUPDATE\s+([a-z_0-9]+)\s+SET",
    re.I | re.S)


def _module_files(module: str) -> list[pathlib.Path]:
    """Source files of one module, excluding tests and migrations."""
    return sorted(
        p for p in (BACKEND / module).rglob("*.py")
        if "__pycache__" not in p.parts and "tests" not in p.parts
        and "migrations" not in p.parts)


def _owner_of_table() -> dict[str, str]:
    """table -> owning module, derived from where the model that declares it lives."""
    owners: dict[str, str] = {}
    for module in SCANNED:
        for path in (BACKEND / module).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for name in TABLENAME_RE.findall(path.read_text(encoding="utf8", errors="replace")):
                owners[name] = module
    return owners


OWNED_BY_MODELS = _owner_of_table()


def test_ownership_could_actually_be_derived():
    """A guard on the guard. If the models stop matching the pattern this scans for, every test
    below starts passing vacuously — which is the failure mode this whole file exists to name."""
    assert len(OWNED_BY_MODELS) >= 15, (
        f"only found {len(OWNED_BY_MODELS)} owned tables: {sorted(OWNED_BY_MODELS)}. The "
        f"__tablename__ scan is not finding the models, so the checks below prove nothing.")
    for module in SCANNED:
        if module in ("intake",):        # owns no tables yet — reconciliation is pure
            continue
        assert module in OWNED_BY_MODELS.values(), f"{module} appears to own no tables"


@pytest.mark.parametrize("module", SCANNED)
def test_a_module_writes_only_its_own_tables(module: str):
    trespasses = []
    for path in _module_files(module):
        text = path.read_text(encoding="utf8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in WRITE_RE.finditer(line):
                table = m.group(1) or m.group(2)
                owner = OWNED_BY_MODELS.get(table)
                if owner is not None and owner != module:
                    trespasses.append(
                        f"{path.relative_to(BACKEND).as_posix()}:{lineno} writes `{table}` "
                        f"(owned by `{owner}`)")
    assert not trespasses, (
        f"`{module}` writes tables it does not own:\n  " + "\n  ".join(trespasses)
        + "\n\nModules integrate through tables, and a produced table is the contract. Two "
          "writers is not a contract. Read the other module's tables with SQL as much as you "
          "like; to WRITE them, call that module's own entry point, or the work belongs there."
    )
