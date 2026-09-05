"""Every migration is reachable, and the chain is one unbroken line.

WHY THIS EXISTS. On 2026-09-05 six migrations (0008-0013) sat on disk, imported cleanly, and were
asserted on by their modules' own tests — and Alembic could not see any of them, because their
directories were missing from `version_locations` in alembic.ini. `alembic upgrade head` ran to
0007 and reported success. Nothing was wrong; the work simply was not there.

That is the same shape as the trap `pytest.ini` documents about `testpaths`: a path missing from a
registry is not an error, it is an absence, and absences report green. Both traps are now covered by
a test rather than by remembering.
"""
from __future__ import annotations

import configparser
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parent.parent
REVISION_RE = re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.M)
DOWN_RE = re.compile(r'^down_revision\s*=\s*(?:["\']([^"\']+)["\']|None)', re.M)


def _configured_locations() -> list[pathlib.Path]:
    cfg = configparser.ConfigParser()
    cfg.read(BACKEND / "alembic.ini")
    raw = cfg["alembic"]["version_locations"]
    return [BACKEND / p for p in raw.split()]


def _migration_files() -> list[pathlib.Path]:
    """Every file on disk that declares a revision, wherever it lives."""
    out = []
    for path in BACKEND.rglob("*.py"):
        if "migrations" not in path.parts or path.name.startswith("_"):
            continue
        if "__pycache__" in path.parts or path.name == "env.py":
            continue
        if REVISION_RE.search(path.read_text(encoding="utf8", errors="replace")):
            out.append(path)
    return sorted(out)


def _revisions() -> dict[str, tuple[str | None, pathlib.Path]]:
    revs = {}
    for f in _migration_files():
        text = f.read_text(encoding="utf8", errors="replace")
        rev = REVISION_RE.search(text).group(1)
        down_match = DOWN_RE.search(text)
        down = down_match.group(1) if down_match else None
        revs[rev] = (down, f)
    return revs


def test_every_migration_directory_is_registered():
    """A revision file Alembic cannot see is not an error — it is an absence, and absences report
    green. This is the check that would have caught six invisible migrations."""
    configured = {p.resolve() for p in _configured_locations()}
    missing = sorted({f.parent.resolve() for f in _migration_files()} - configured)
    assert not missing, (
        "migration directories not listed in alembic.ini `version_locations`: "
        + ", ".join(str(p.relative_to(BACKEND)) for p in missing)
        + ". `alembic upgrade head` will skip them silently and report success."
    )


def test_every_configured_location_exists():
    """The mirror failure: a stale entry pointing at a directory that has moved."""
    missing = [p for p in _configured_locations() if not p.is_dir()]
    assert not missing, f"version_locations names directories that do not exist: {missing}"


def test_the_chain_is_unbroken():
    """One line, no orphans. A revision whose `down_revision` names nothing real splits the chain
    into two heads, and Alembic will refuse to upgrade rather than pick one."""
    revs = _revisions()
    dangling = {rev: down for rev, (down, _) in revs.items()
                if down is not None and down not in revs}
    assert not dangling, f"down_revision points at revisions that do not exist: {dangling}"


def test_there_is_exactly_one_base_and_one_head():
    revs = _revisions()
    bases = [r for r, (down, _) in revs.items() if down is None]
    downs = {down for down, _ in revs.values() if down}
    heads = [r for r in revs if r not in downs]
    assert len(bases) == 1, f"expected one base revision, found {sorted(bases)}"
    assert len(heads) == 1, (
        f"expected one head, found {sorted(heads)} — a fork means `upgrade head` is ambiguous")


def test_no_two_migrations_claim_the_same_revision():
    """Two files with the same `revision` is a merge conflict that resolved badly, and Alembic will
    load whichever it happens to see first."""
    seen: dict[str, pathlib.Path] = {}
    clashes = []
    for f in _migration_files():
        rev = REVISION_RE.search(f.read_text(encoding="utf8", errors="replace")).group(1)
        if rev in seen:
            clashes.append((rev, seen[rev].name, f.name))
        seen[rev] = f
    assert not clashes, f"duplicate revision ids: {clashes}"


def test_the_head_reaches_the_base():
    """Walk it, rather than trusting the counts above to imply connectivity."""
    revs = _revisions()
    downs = {down for down, _ in revs.values() if down}
    head = next(r for r in revs if r not in downs)
    walked, cursor = 0, head
    while cursor is not None:
        walked += 1
        cursor = revs[cursor][0]
        assert walked <= len(revs) + 1, "cycle in the migration chain"
    assert walked == len(revs), (
        f"walked {walked} revisions from head but {len(revs)} exist — some are unreachable")
