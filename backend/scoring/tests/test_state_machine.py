"""The state machine's shape, checked without a database.

The trigger in 0008 is what actually enforces these rules at runtime; these tests guard the two
things a trigger cannot guard itself — that the map in `models.py` and the copy embedded in the
migration have not drifted apart, and that the machine's shape still says what the design says.
"""
from __future__ import annotations

import importlib.util
import pathlib

from scoring.models import (ARTIFACT_STATES, ARTIFACT_TRANSITIONS, TERMINAL_STATES)

MIGRATION = (pathlib.Path(__file__).resolve().parent.parent
             / "migrations" / "0008_scoring_tables.py")


def _migration():
    spec = importlib.util.spec_from_file_location("scoring_0008", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_copy_of_the_transitions_has_not_drifted():
    """`models.py` and the migration each hold the map. The duplication is deliberate — a
    migration must run at the revision it was written without importing code that has since
    moved — so something has to notice when they disagree. This is that something."""
    assert _migration()._TRANSITIONS == ARTIFACT_TRANSITIONS, (
        "scoring/models.py ARTIFACT_TRANSITIONS and 0008's _TRANSITIONS disagree. "
        "Change both, or the database will enforce a machine the code does not believe in."
    )


def test_every_transition_target_is_a_real_state():
    unknown = {to for moves in ARTIFACT_TRANSITIONS.values() for to in moves
               } - set(ARTIFACT_STATES)
    assert not unknown, f"transitions point at states that do not exist: {sorted(unknown)}"


def test_every_state_appears_in_the_transition_map():
    missing = set(ARTIFACT_STATES) - set(ARTIFACT_TRANSITIONS)
    assert not missing, f"states with no entry in the map: {sorted(missing)}"


def test_only_a_teacher_may_release():
    """The authority claim the product rests on. If a machine can reach `released`, the system is
    scoring students unsupervised and the review step is decorative."""
    releasers = {frm: moves["released"] for frm, moves in ARTIFACT_TRANSITIONS.items()
                 if "released" in moves}
    assert releasers, "nothing can reach `released` — the machine is a dead end"
    assert set(releasers.values()) == {"teacher"}, (
        f"a non-teacher actor can release: {releasers}")


def test_released_and_withheld_are_terminal():
    """Terminal in the state machine, which is not the same as final. A later iteration supersedes
    via a NEW artifact (artifact.superseded_by_artifact_id) rather than by moving this one out of
    `released` — release is never final, and that is expressed by supersession, not by a
    transition backwards."""
    assert TERMINAL_STATES == {"released", "withheld"}


def test_withheld_is_reachable_from_every_non_terminal_state():
    """A teacher can always stop. If some state could not be withheld from, an artifact could get
    stuck somewhere a human cannot end it, and the error queue would stop being a view over states
    a teacher owns."""
    stuck = [s for s in ARTIFACT_STATES
             if s not in TERMINAL_STATES and "withheld" not in ARTIFACT_TRANSITIONS[s]]
    assert not stuck, f"states a teacher cannot withhold from: {stuck}"


def test_no_state_is_unreachable():
    """Except `unbound`, which is where everything starts."""
    reachable = {to for moves in ARTIFACT_TRANSITIONS.values() for to in moves} | {"unbound"}
    orphans = set(ARTIFACT_STATES) - reachable
    assert not orphans, f"states nothing can reach: {sorted(orphans)}"


def test_scoring_cannot_skip_review():
    """`scored` must not reach `released` directly. The teacher sees the score with its verified
    evidence and decides; composing and reviewing are not optional steps to be routed around."""
    assert "released" not in ARTIFACT_TRANSITIONS["scored"]
    assert "released" not in ARTIFACT_TRANSITIONS["composed"]
