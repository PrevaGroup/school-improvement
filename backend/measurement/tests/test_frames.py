"""Frame resolution — the properties reproducibility actually rests on."""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

from measurement.frames import (UnknownDefinitionKey, admits, canonical, definition_hash,
                                resolve, validate)
from measurement.models import DEFINITION_KEYS, FRAME_STATUSES

MIGRATION = (pathlib.Path(__file__).resolve().parent.parent
             / "migrations" / "0010_measurement_frames.py")
SQL = MIGRATION.read_text(encoding="utf8")


def ev(**kw):
    base = {"event_id": "e1", "window_label": "fall 2026", "node_id": "ci",
            "scorer_type": "ai", "iteration": "final", "scrutiny_passes": 1,
            "is_measurement_occasion": True, "enters_calibration": True,
            "set_override_id": None}
    return base | kw


# --------------------------------------------------------------------------- #
# Identity — what makes an estimate attributable
# --------------------------------------------------------------------------- #
def test_hash_is_stable_across_key_and_list_order():
    """Two definitions that admit the same observations must hash the same however they were
    typed, or the hash reports edits nobody made and every frame looks perpetually changed."""
    a = {"windows": ["fall 2026", "spring 2027"], "scorer_types": ["ai", "teacher"]}
    b = {"scorer_types": ["teacher", "ai"], "windows": ["spring 2027", "fall 2026"]}
    assert definition_hash(a) == definition_hash(b)


def test_hash_changes_when_admission_changes():
    a = {"windows": ["fall 2026"]}
    b = {"windows": ["fall 2026", "spring 2027"]}
    assert definition_hash(a) != definition_hash(b)


def test_canonical_form_has_no_incidental_whitespace():
    assert " " not in canonical({"windows": ["fall 2026"]}).replace("fall 2026", "x")


# --------------------------------------------------------------------------- #
# An unknown key is fatal, not ignored
# --------------------------------------------------------------------------- #
def test_unknown_key_raises_rather_than_being_skipped():
    """A typo silently skipped produces a frame admitting more than its author intended, and the
    estimate that follows looks perfectly healthy. Same reasoning as the eval design refusing to
    let an unknown grader pass quietly."""
    with pytest.raises(UnknownDefinitionKey) as e:
        validate({"windows": ["fall 2026"], "window": ["spring 2027"]})
    assert "window" in str(e.value)


def test_every_documented_key_is_accepted():
    validate({k: None for k in DEFINITION_KEYS})


# --------------------------------------------------------------------------- #
# Admission
# --------------------------------------------------------------------------- #
def test_empty_definition_admits_everything():
    """A definition names what it RESTRICTS. Defaults that exclude would make a definition's
    meaning depend on the resolver's version — the opposite of reproducible."""
    assert admits({}, ev())


@pytest.mark.parametrize("key,field,allowed,bad", [
    ("windows", "window_label", ["fall 2026"], "spring 2027"),
    ("node_ids", "node_id", ["ci", "ev"], "org"),
    ("scorer_types", "scorer_type", ["ai", "expert"], "teacher"),
    ("iterations", "iteration", ["final"], "draft"),
])
def test_each_dimension_narrows(key, field, allowed, bad):
    assert admits({key: allowed}, ev())
    assert not admits({key: allowed}, ev(**{field: bad}))


def test_measurement_occasions_only():
    d = {"measurement_occasions_only": True}
    assert admits(d, ev(is_measurement_occasion=True))
    assert not admits(d, ev(is_measurement_occasion=False))


def test_escalated_scores_can_be_excluded():
    """Escalated and unescalated scores come from different administrations of the same rater."""
    assert admits({}, ev(scrutiny_passes=2))
    assert not admits({"include_escalated": False}, ev(scrutiny_passes=2))
    assert admits({"include_escalated": False}, ev(scrutiny_passes=1))


def test_set_overrides_can_be_excluded():
    """One judgment covering many artifacts. Admitting every covered row multiplies a single
    decision against everyone else's."""
    assert not admits({"include_set_overrides": False}, ev(set_override_id="so-1"))
    assert admits({"include_set_overrides": False}, ev(set_override_id=None))


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def test_resolve_is_deterministic_over_the_same_events():
    d = {"windows": ["fall 2026"]}
    events = [ev(event_id=f"e{i}", window_label="fall 2026" if i % 2 else "spring 2027")
              for i in range(10)]
    assert resolve(d, events) == resolve(d, events)


def test_calibration_membership_is_carried_not_recomputed():
    """The frame decides what is measurable; the event decides what moves parameters. Two
    memberships, and the frame does not get to revisit the second."""
    out = resolve({}, [ev(event_id="a", enters_calibration=True),
                       ev(event_id="b", enters_calibration=False)])
    assert {m["event_id"]: m["enters_calibration"] for m in out} == {"a": True, "b": False}


def test_frame_can_hold_an_event_without_calibrating_it():
    """Three sets, not two: a superseded draft is in the record and the frame, out of the
    calibration. If resolution forced them together this distinction would not survive."""
    out = resolve({}, [ev(event_id="draft", iteration="draft", enters_calibration=False)])
    assert out == [{"event_id": "draft", "enters_calibration": False}]


# --------------------------------------------------------------------------- #
# The migration's invariants
# --------------------------------------------------------------------------- #
def test_active_frame_definition_is_frozen_by_trigger():
    """A number published against version 3 has to keep meaning what it meant."""
    assert "measurement_freeze_active_frame" in SQL
    assert "NEW.definition IS DISTINCT FROM OLD.definition" in SQL


def test_tombstone_marks_frames_stale_in_the_same_transaction():
    """A nightly sweep would leave a window in which a published figure silently rests on
    observations that no longer exist."""
    assert "measurement_tombstone_marks_frames_stale" in SQL
    assert "BEFORE INSERT ON measurement_deletion_tombstone" in SQL
    assert "SET status = 'stale'" in SQL


def test_stale_is_a_status_a_frame_can_hold():
    assert "stale" in FRAME_STATUSES


def test_no_estimator_shipped_here():
    """Fits belong to Phase 6. A half-built estimator now would be a shape guessed before there is
    anything to fit against."""
    for forbidden in ("facet_estimate", "mfrm_run", "infit", "outfit"):
        assert forbidden not in SQL


def test_migration_follows_the_roster_revision():
    spec = importlib.util.spec_from_file_location("measurement_0010", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (mod.revision, mod.down_revision) == ("0010", "0009")
