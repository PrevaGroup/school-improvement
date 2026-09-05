"""The driver's assembly — the facet stamp, the idempotency key, and where an artifact goes next.

Everything here is a pure function of its arguments, which is the reason those functions exist
separately from the loop that calls them: the parts of the driver that are easy to get wrong are
the parts that assemble a row, and they should not need a database to check.

The parts that DO need one — the trigger, the append-only rule, the release authority — are proven
against real Postgres by `sql/20_scoring_smoketest.sql`, because a trigger created without error
says nothing about whether it fires.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from app.vocab import SCORE_STATUS_IDS
from scoring.prompts import fingerprint
from scoring.rater import RaterIdentity
from scoring.run_scoring import (ConfigurationError, check_configuration, enters_calibration,
                                 event_rows, idempotency_key, next_state, trait_set_version)
from scoring.score import Outcome

ARTIFACT = {
    "artifact_id": "art-1", "run_id": "run-9", "student_id": "stu-1", "section_id": "sec-1",
    "task_id": "task-1", "iteration": "final", "window_label": "fall 2026",
    "content_hash": "h", "source_uri": None, "tenant_id": "public", "visibility": "public",
}

IDENTITY = RaterIdentity("cfg-1", "claude-opus-5", "high", fingerprint(), "1")


def outcome(status="scored", level=3.0, node="n1"):
    return Outcome(node_id=node, node_version_id=f"{node}-v2", status=status, level=level,
                   confidence="high", reason="r", evidence={"proposed": 1, "kept": [],
                                                            "dropped": [], "norm_version": "1"})


# ------------------------------------------------------------------ idempotency


def test_the_idempotency_key_does_not_contain_the_run_id():
    """A resumed run is the same run doing the same work. Keying on the run id would make every
    retry a fresh observation — a measurement bug wearing a throughput bug's clothes."""
    key = idempotency_key("art-1", "n1", "cfg-1", 1)
    assert "run-9" not in key
    assert key == idempotency_key("art-1", "n1", "cfg-1", 1)


def test_the_key_separates_the_things_that_are_genuinely_different_observations():
    base = idempotency_key("art-1", "n1", "cfg-1", 1)
    assert base != idempotency_key("art-2", "n1", "cfg-1", 1)   # different text
    assert base != idempotency_key("art-1", "n2", "cfg-1", 1)   # different item
    assert base != idempotency_key("art-1", "n1", "cfg-2", 1)   # different rater
    assert base != idempotency_key("art-1", "n1", "cfg-1", 2)   # escalated pass


# ------------------------------------------------------------------ the trait set stamp


def test_the_trait_set_version_is_order_sensitive():
    """A different order is a different administration — the traits were presented differently."""
    assert trait_set_version(["a", "b"]) != trait_set_version(["b", "a"])
    assert trait_set_version(["a", "b"]) == trait_set_version(["a", "b"])


def test_the_trait_set_version_changes_when_a_wording_changes():
    assert trait_set_version(["n1-v1", "n2-v1"]) != trait_set_version(["n1-v2", "n2-v1"])


# ------------------------------------------------------------------ calibration membership


def test_only_a_scored_outcome_on_a_measurement_occasion_is_proposed_for_calibration():
    assert enters_calibration(outcome("scored"), True) is True
    assert enters_calibration(outcome("abstained", None), True) is False
    assert enters_calibration(outcome("no_verified_evidence", None), True) is False


def test_a_draft_never_enters_calibration():
    """Drafts are low stakes for the student and mistakes there are useful. Letting them move the
    parameters drives revision at the stage where exploration is the point."""
    assert enters_calibration(outcome("scored"), False) is False


# ------------------------------------------------------------------ the row


def test_every_status_written_is_in_cores_vocabulary():
    rows = event_rows(ARTIFACT, [outcome("scored"), outcome("abstained", None, "n2")],
                      IDENTITY, "ts-x", True)
    assert all(r["status"] in SCORE_STATUS_IDS for r in rows)


def test_a_status_outside_the_vocabulary_is_refused_here_rather_than_by_the_database():
    with pytest.raises(ValueError, match="SCORE_STATUSES"):
        event_rows(ARTIFACT, [outcome("pretty_good")], IDENTITY, "ts-x", True)


def test_a_level_exists_if_and_only_if_the_status_is_scored():
    """The same rule the CHECK constraint enforces. Asserted here too because a row that reaches
    the database and is rejected has already cost a model call."""
    rows = event_rows(ARTIFACT, [outcome("scored"), outcome("abstained", None, "n2"),
                                 outcome("not_scorable", None, "n3")], IDENTITY, "ts-x", True)
    for r in rows:
        assert (r["level"] is not None) == (r["status"] == "scored")


def test_the_form_variant_stays_a_separate_column_and_stays_empty():
    """There are no alternate forms yet. Folding one into rubric_version later would make its
    effect unrecoverable — the hidden-facet failure the construct audit found in the existing
    rubric data, and the reason this column exists before anything fills it."""
    r = event_rows(ARTIFACT, [outcome()], IDENTITY, "ts-x", True)[0]
    assert r["form_variant"] is None
    assert r["rubric_version"] == "n1-v2"


def test_a_machine_rater_is_its_configuration_and_has_no_individual_identity():
    """A human is identified individually because rater severity cannot be estimated from an
    anonymous pool. A machine has no individual — the configuration IS the rater."""
    r = event_rows(ARTIFACT, [outcome()], IDENTITY, "ts-x", True)[0]
    assert r["scorer_type"] == "ai"
    assert r["scorer_id"] is None
    assert r["scoring_configuration_id"] == "cfg-1"
    assert r["human_blind"] is None


def test_the_binding_is_denormalised_onto_every_event():
    """The event is self-describing: a score that needs a join to say whose it is stops being
    readable the moment the artifact row is touched."""
    r = event_rows(ARTIFACT, [outcome()], IDENTITY, "ts-x", True)[0]
    for field in ("student_id", "section_id", "task_id", "iteration", "window_label", "run_id"):
        assert r[field] == ARTIFACT[field]


def test_every_event_gets_its_own_id():
    rows = event_rows(ARTIFACT, [outcome(node="n1"), outcome(node="n2")], IDENTITY, "ts-x", True)
    assert rows[0]["event_id"] != rows[1]["event_id"]
    assert rows[0]["idempotency_key"] != rows[1]["idempotency_key"]


def test_the_evidence_is_serialised_as_json_for_the_jsonb_column():
    r = event_rows(ARTIFACT, [outcome()], IDENTITY, "ts-x", True)[0]
    assert isinstance(r["evidence"], str) and r["evidence"].startswith("{")


# ------------------------------------------------------------------ where it goes next


def test_a_fully_unscorable_artifact_goes_to_not_scorable():
    state, reason = next_state([outcome("not_scorable", None, "n1"),
                                outcome("not_scorable", None, "n2")])
    assert state == "not_scorable"


def test_abstentions_still_leave_the_artifact_scored():
    """`scored` means every criterion has an outcome, including abstentions. Holding the artifact
    back because one criterion needs a human would stall the eleven that do not."""
    state, _ = next_state([outcome("scored"), outcome("abstained", None, "n2"),
                           outcome("no_verified_evidence", None, "n3")])
    assert state == "scored"


def test_a_mixture_of_not_scorable_and_scored_is_loud():
    """not_scorable is a fact about the artifact, not about a criterion. It cannot happen today;
    if it ever does, rounding to whichever is more common would bury the cause."""
    with pytest.raises(ValueError, match="not_scorable is a fact about the artifact"):
        next_state([outcome("scored"), outcome("not_scorable", None, "n2")])


# ------------------------------------------------------------------ the configuration gate


def test_a_configuration_whose_prompts_have_moved_is_refused():
    stale = RaterIdentity("cfg-old", "claude-opus-5", "high",
                          {"evidence": {"version": "ev.1", "sha256": "0000000000000000"},
                           "score": {"version": "sc.1", "sha256": "1111111111111111"}}, "1")
    with pytest.raises(ConfigurationError, match="not the one that was promoted"):
        check_configuration(stale)


def test_a_configuration_that_matches_the_text_on_disk_passes():
    check_configuration(IDENTITY)


def test_a_floating_model_alias_is_not_a_pinned_rater():
    """An alias that resolves to a new build changes the rater without changing the record, and
    every score before and after looks identical."""
    with pytest.raises(ValueError, match="floating alias"):
        RaterIdentity("cfg-x", "claude-opus-latest", "high", fingerprint(), "1")


# ------------------------------------------------------------------ the SQL itself


def test_no_optional_parameter_is_compared_to_null_without_a_type():
    """`AND (:run_id IS NULL OR run_id = :run_id)` looks obviously fine and Postgres refuses it.

    A bind parameter that only ever appears beside IS NULL gives the planner nothing to infer a
    type from, and the whole statement fails with `could not determine data type of parameter $2`
    — at execution, against a real server. Every unit test here passed; the first Cloud Shell run
    did not survive its first query.

    This is a text scan rather than a real check, and it only catches the shape that already bit
    us. That is the honest scope of it: the general problem needs a database, and this is the part
    that can be caught without one.
    """
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("run_scoring.py").read_text(
        encoding="utf8")
    bare = [m.group(0) for m in re.finditer(r"(?<!AS text\)\s)\B:(\w+)\s+IS\s+NULL", src)]
    assert not bare, (
        f"optional bind parameters compared to NULL without a CAST: {bare}. Postgres cannot infer "
        f"a type for them and refuses the statement.")
