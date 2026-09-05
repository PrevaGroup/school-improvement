"""What the review packet says, and — mostly — what it refuses to say.

The prior-observations panel is the most useful thing on the review screen and the easiest place
in the product to state something false, because two numbers side by side are an invitation to
read a trend. Most of this file is about the three filters that stand between the record and that
invitation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scoring.compose import (COMPOSER_VERSION, _PRIOR, build_packet, configuration_of,
                             prior_for_node)

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)

ARTIFACT = {
    "artifact_id": "art-1", "run_id": "run-1", "student_id": "stu-1", "section_id": "sec-1",
    "task_id": "task-2", "iteration": "final", "window_label": "fall 2026",
    "tenant_id": "public", "visibility": "public",
}

LABELS = {
    "n1": {"node_id": "n1", "criterion_label": "Controlling idea",
           "standard_code": "DEMO.CI", "scale_categories": [1, 2, 3, 4]},
    "n2": {"node_id": "n2", "criterion_label": "Use of evidence",
           "standard_code": "DEMO.EV", "scale_categories": [1, 2, 3, 4]},
}


def event(node="n1", status="scored", level=3, **kw):
    e = {
        "event_id": f"ev-{node}", "node_id": node, "status": status, "level": level,
        "confidence": "high", "reason": "because", "reason_code": None,
        "evidence": {"proposed": 2, "norm_version": "1",
                     "kept": [{"span": "a real sentence from the paper"}],
                     "dropped": [{"span": "A SENTENCE THE MODEL INVENTED"}]},
        "rubric_version": f"{node}-v1", "trait_set_version": "ts-x", "form_variant": None,
        "scoring_configuration_id": "cfg-1", "scorer_type": "ai", "scrutiny_passes": 1,
        "is_measurement_occasion": True, "created_at": T0,
    }
    e.update(kw)
    return e


def prior(node="n1", level=2, config="cfg-1", task="task-1", days=-30):
    return {"node_id": node, "task_id": task, "iteration": "final", "window_label": "spring 2026",
            "level": level, "scoring_configuration_id": config, "artifact_id": "art-0",
            "created_at": T0 + timedelta(days=days)}


# ------------------------------------------------------------------ the rater


def test_two_configurations_on_one_artifact_is_a_contradiction_not_a_summary():
    """The pin exists so every event on one artifact carries one configuration. A packet that
    averaged over two would present two raters' work as one opinion."""
    with pytest.raises(ValueError, match="cannot name one rater"):
        configuration_of([event(), event(node="n2", scoring_configuration_id="cfg-2")])


def test_the_stamp_comes_from_the_events_not_from_a_second_read():
    """A packet that re-read the configuration could claim a rater the scores were not produced
    under — which is exactly what a stamp is supposed to make impossible."""
    p = build_packet(ARTIFACT, [event(), event(node="n2")], LABELS, [])
    assert p["stamp"]["scoring_configuration_id"] == "cfg-1"
    assert p["stamp"]["trait_set_version"] == "ts-x"
    assert p["stamp"]["scrutiny_passes"] == 1
    assert p["stamp"]["form_variant"] is None


# ------------------------------------------------------------------ evidence


def test_a_dropped_span_never_reaches_the_teacher_as_text():
    """Showing a teacher the sentences a model invented invites reading the invention as
    evidence. The count goes in the packet so the drop is visible; score_event keeps the full
    text for whoever is debugging the pipeline rather than reviewing a paper."""
    p = build_packet(ARTIFACT, [event()], LABELS, [])
    c = p["criteria"][0]
    assert c["evidence"] == ["a real sentence from the paper"]
    assert c["evidence_dropped"] == 1
    assert "INVENTED" not in str(p)


def test_a_criterion_that_needs_a_human_is_flagged_and_carries_no_level():
    p = build_packet(ARTIFACT, [event(), event(node="n2", status="abstained", level=None)],
                     LABELS, [])
    assert p["needs_human"] == ["n2"]
    by_node = {c["node_id"]: c for c in p["criteria"]}
    assert by_node["n2"]["needs_human"] is True
    assert by_node["n2"]["level"] is None
    assert by_node["n1"]["needs_human"] is False


def test_no_verified_evidence_also_routes_to_a_human():
    p = build_packet(ARTIFACT, [event(status="no_verified_evidence", level=None)], LABELS, [])
    assert p["needs_human"] == ["n1"]


def test_the_criterion_label_comes_from_the_registry():
    """The event stores a node id. A packet showing raw identifiers to a teacher would be asking
    them to review something they cannot read."""
    p = build_packet(ARTIFACT, [event()], LABELS, [])
    assert p["criteria"][0]["criterion_label"] == "Controlling idea"
    assert p["criteria"][0]["scale_categories"] == [1, 2, 3, 4]


# ------------------------------------------------------------------ prior observations


def test_a_prior_level_from_the_same_rater_is_marked_comparable():
    out = prior_for_node([prior()], "n1", "cfg-1")
    assert out[0]["same_rater"] is True
    assert out[0]["level"] == 2.0


def test_a_prior_level_from_a_different_rater_is_marked_and_the_packet_says_why():
    """The pin holds within one section x task x iteration, deliberately — that is the scope a
    teacher compares within. Across tasks it does not, so two priors can be two raters."""
    p = build_packet(ARTIFACT, [event()], LABELS, [prior(config="cfg-OLD")])
    assert p["prior_rater_mismatch"] is True
    assert "not directly comparable" in p["prior_note"]
    assert p["criteria"][0]["prior"][0]["same_rater"] is False


def test_a_packet_with_no_mismatch_carries_no_qualification():
    """A note attached to everything is a note nobody reads."""
    p = build_packet(ARTIFACT, [event()], LABELS, [prior()])
    assert p["prior_rater_mismatch"] is False
    assert p["prior_note"] is None


def test_prior_observations_are_matched_by_node_not_by_label():
    """Two criteria that both sound like evidence are two nodes. Putting their levels in one row
    compares two different things, and the node identifier is the identity — so this is a join,
    not a judgment."""
    out = prior_for_node([prior(node="n2", level=4)], "n1", "cfg-1")
    assert out == []


def test_priors_keep_the_task_they_came_from():
    """A level with no occasion attached is a number floating free of what produced it."""
    out = prior_for_node([prior(task="task-1")], "n1", "cfg-1")
    assert out[0]["task_id"] == "task-1"
    assert out[0]["window_label"] == "spring 2026"


# ------------------------------------------------------------------ the query's own filters


def test_the_prior_query_excludes_drafts():
    """A draft is scored and is not a measurement occasion. A draft level beside a final one reads
    as growth within an assignment, and the user's ruling is explicit: a draft is not a valid
    comparison point. Drafts are low stakes and mistakes there are useful."""
    sql = str(_PRIOR)
    assert "is_measurement_occasion IS TRUE" in sql


def test_the_prior_query_takes_only_scored_outcomes_and_never_this_artifact():
    sql = str(_PRIOR)
    assert "status = 'scored'" in sql
    assert "artifact_id <> :artifact_id" in sql
    assert "student_id = :student_id" in sql


def test_the_packet_records_which_assembler_built_it():
    """A packet's shape is part of what a teacher saw, so it is stamped like the rater is."""
    p = build_packet(ARTIFACT, [event()], LABELS, [])
    assert p["composer_version"] == COMPOSER_VERSION
