"""The score record's shape — the facets that are unrecoverable if they are not logged now.

These assert against the mapped columns rather than a live database. The point is not that
SQLAlchemy works; it is that a future edit which quietly drops a facet fails here, with a message
saying why that facet exists. The construct audit found hidden facets in existing rubric data that
could not be recovered after the fact, and this is the guard against repeating it.
"""
from __future__ import annotations

import pytest

from app.vocab import SCORE_STATUS_IDS, SCORE_STATUS_TO_VALUE_STATUS, VALUE_STATUS_IDS
from scoring.models import Artifact, ArtifactStateTransition, ScoreEvent

COLS = {c.name for c in ScoreEvent.__table__.columns}


@pytest.mark.parametrize("col,why", [
    ("run_id",        "which run produced it"),
    ("student_id",    "binding key"),
    ("section_id",    "binding key — also scopes rubric version and reviewer"),
    ("task_id",       "binding key — determines the trait set"),
    ("iteration",     "binding key — draft and final are different occasions"),
    ("window_label",  "growth intervals pair on declared labels, not elapsed time"),
    ("node_id",       "the item: standard x criterion x scale x grade band"),
    ("rubric_version", "a teacher edit produces a new item set"),
    ("form_variant",  "SEPARATE from rubric_version: the alternate form is its own facet, and "
                      "folding it into version makes its effect unrecoverable"),
    ("scoring_configuration_id", "the rater identity — model, prompts, effort, normalization"),
    ("scorer_type",   "ai, teacher and expert differ in how drift is estimable"),
    ("scorer_id",     "human raters are individual: severity cannot be estimated from a pool"),
    ("human_blind",   "an informed score is not an independent rating in a calibration design"),
    ("scrutiny_passes", "escalated scores come from a different administration"),
    ("escalation_trigger", "escalated papers are not a random subset"),
    ("status",        "abstained, not_scorable and withheld are different facts"),
    ("level",         "the number, when there is one"),
    ("evidence",      "the verified spans the level rests on, and what was dropped"),
    ("is_measurement_occasion", "the registry declares which iteration counts"),
    ("enters_calibration", "record, frame and calibration are three memberships"),
    ("revised_after_feedback", "a feedback-mediated final is not unaided performance"),
    ("supersedes_event_id", "an override appends, referencing what it disagrees with"),
    ("set_override_id", "one judgment over many artifacts is one judgment"),
    ("idempotency_key", "a resumed run must not double the observations"),
])
def test_facet_is_stamped(col: str, why: str):
    assert col in COLS, f"score_event lost `{col}` — {why}"


def test_status_vocabulary_comes_from_core():
    """The module must not invent its own missingness words. Naming them in core is what stopped
    two subsystems meaning slightly different things by 'not collected'."""
    assert set(SCORE_STATUS_IDS) == {
        "scored", "withheld", "not_scorable", "no_verified_evidence", "abstained", "unbound"}
    assert set(SCORE_STATUS_TO_VALUE_STATUS) == set(SCORE_STATUS_IDS)
    assert set(SCORE_STATUS_TO_VALUE_STATUS.values()) <= set(VALUE_STATUS_IDS)


def test_score_event_has_no_updated_at():
    """Append-only means there is no operation that would set one. A column that could never be
    written is an invitation to write it."""
    assert "updated_at" not in COLS


def test_override_and_supersession_are_different_relations():
    """The distinction the override stream depends on: `supersedes_event_id` is a different
    judgment about the same text; `superseded_by_artifact_id` is a different text. If these ever
    collapse into one column, 'we scored this wrong' and 'they wrote it again' become the same
    fact, and the calibration data stops meaning anything."""
    assert "supersedes_event_id" in COLS
    assert "superseded_by_artifact_id" not in COLS
    artifact_cols = {c.name for c in Artifact.__table__.columns}
    assert "superseded_by_artifact_id" in artifact_cols
    assert "supersedes_event_id" not in artifact_cols


def test_idempotency_key_is_unique():
    uniques = {tuple(sorted(c.columns.keys()))
               for c in ScoreEvent.__table__.constraints
               if c.__class__.__name__ == "UniqueConstraint"}
    assert ("idempotency_key",) in uniques, (
        "without this, a resumed run silently doubles observations — a measurement bug, not a "
        "throughput one")


def test_level_is_constrained_to_scored_rows():
    """A level without a score, or a score without a level, is a row that means nothing."""
    names = {c.name for c in ScoreEvent.__table__.constraints if c.name}
    assert "ck_score_event_level_matches_status" in names


def test_student_work_tables_carry_tenancy():
    """They hold identifiable student writing. RLS is switched on separately and deliberately, but
    the columns have to be there from the first migration or it is a retrofit."""
    for model in (Artifact, ScoreEvent, ArtifactStateTransition):
        cols = {c.name for c in model.__table__.columns}
        assert {"tenant_id", "visibility"} <= cols, f"{model.__tablename__} lacks tenancy columns"


def test_transitions_record_their_actor():
    """'Who released this' has to be answerable from the record, not from an application log."""
    cols = {c.name for c in ArtifactStateTransition.__table__.columns}
    assert {"from_state", "to_state", "actor_type", "actor_id"} <= cols
