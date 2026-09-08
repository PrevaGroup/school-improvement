"""Paired cases, and the two ways a comparison quietly reports nothing wrong.

Three of the five stop conditions are comparisons: the same paper among different classmates,
with conventions errors added, or at two scrutiny levels. Neither arm means anything alone — a
score of 3 is not evidence of anything; a 3 that becomes a 2 when nothing on the scale changed is
the whole finding.

Both silent failures produce a delta of ZERO, and zero is the passing answer for every one of
these conditions. That is why an incomplete pair and a mismatched configuration are errors here
rather than results.
"""
from __future__ import annotations

import pytest

from evals.compare import (BASELINE, VARIANT, PairError, as_cohort_arms, as_matched_pairs,
                           compare, pairs_from_cases)


def arm(config="cfg-1", **levels):
    return {"scoring_configuration_id": config,
            "scores": [{"node_id": k, "status": "scored" if v is not None else "abstained",
                        "level": v} for k, v in levels.items()]}


# ------------------------------------------------------------------ the delta

def test_a_pair_that_did_not_move_reports_no_movement():
    c = compare("p1", {BASELINE: arm(n1=3, n2=4), VARIANT: arm(n1=3, n2=4)})
    assert c.moved == [] and c.max_abs_delta == 0


def test_the_delta_is_variant_minus_baseline():
    """Sign convention, and it carries meaning downstream: a scorer marking the manipulated arm
    DOWN is the expected conventions failure, and marking it up is stranger."""
    c = compare("p1", {BASELINE: arm(n1=3), VARIANT: arm(n1=2)})
    assert c.deltas[0].delta == -1


def test_every_criterion_gets_a_row_even_when_it_did_not_move():
    c = compare("p1", {BASELINE: arm(n1=3, n2=4), VARIANT: arm(n1=2, n2=4)})
    assert len(c.deltas) == 2
    assert [d.node_id for d in c.moved] == ["n1"]


# ------------------------------------------------------------------ incomplete is an error

def test_a_pair_with_one_arm_is_an_error_not_a_zero():
    """The quiet failure. An arm that errored or was never written leaves its sibling ungraded,
    and a delta computed against a missing arm is zero — the passing answer."""
    with pytest.raises(PairError, match="missing its variant arm"):
        compare("p1", {BASELINE: arm(n1=3)})
    with pytest.raises(PairError, match="missing its baseline arm"):
        compare("p1", {VARIANT: arm(n1=3)})


def test_the_error_says_why_a_zero_would_have_been_wrong():
    with pytest.raises(PairError, match="pass produced by an absence"):
        compare("p1", {BASELINE: arm(n1=3)})


def test_an_empty_arm_counts_as_missing():
    with pytest.raises(PairError, match="missing"):
        compare("p1", {BASELINE: arm(n1=3), VARIANT: {}})


# ------------------------------------------------------------------ one rater, or no answer

def test_two_configurations_is_refused_rather_than_reported():
    """A configuration version IS a rater. Two arms under two raters measures the rater change and
    the manipulation together, with no way afterwards to separate them."""
    with pytest.raises(PairError, match="rater change"):
        compare("p1", {BASELINE: arm(config="cfg-1", n1=3),
                       VARIANT: arm(config="cfg-2", n1=2)})


def test_the_configuration_that_ran_is_reported():
    c = compare("p1", {BASELINE: arm(config="cfg-7", n1=3), VARIANT: arm(config="cfg-7", n1=3)})
    assert c.config_id == "cfg-7"


# ------------------------------------------------------------------ abstention is not zero

def test_an_abstention_on_one_arm_is_not_counted_as_movement():
    """"We could not place this" is not a level, and subtracting from it would turn an abstention
    into "it did not move"."""
    c = compare("p1", {BASELINE: arm(n1=3), VARIANT: arm(n1=None)})
    d = c.deltas[0]
    assert d.delta is None and not d.moved
    assert "no level on the variant" in d.note


def test_an_abstention_is_recorded_rather_than_dropped():
    """A criterion that stops being scorable once conventions errors are added is itself evidence
    about the scorer, and dropping the row would hide it."""
    c = compare("p1", {BASELINE: arm(n1=3, n2=2), VARIANT: arm(n1=None, n2=2)})
    assert len(c.deltas) == 2
    assert any(d.note for d in c.deltas)


def test_a_pair_with_no_criteria_at_all_is_an_error():
    with pytest.raises(PairError, match="no criteria"):
        compare("p1", {BASELINE: arm(), VARIANT: arm()})


# ------------------------------------------------------------------ grouping the suite

def test_cases_group_into_pairs():
    cases = [{"eval_case_id": "c1", "pair_id": "p1", "arm": BASELINE},
             {"eval_case_id": "c2", "pair_id": "p1", "arm": VARIANT},
             {"eval_case_id": "c3", "pair_id": None, "arm": None}]
    got = pairs_from_cases(cases)
    assert set(got) == {"p1"} and set(got["p1"]) == {BASELINE, VARIANT}


def test_an_unnamed_arm_is_a_construction_error():
    with pytest.raises(PairError, match="arm 'left'"):
        pairs_from_cases([{"eval_case_id": "c1", "pair_id": "p1", "arm": "left"}])


def test_three_arms_in_one_pair_is_an_error():
    """Silently keeping two of the three would produce a number, and the number would look fine."""
    with pytest.raises(PairError, match="two baseline arms"):
        pairs_from_cases([{"eval_case_id": "c1", "pair_id": "p1", "arm": BASELINE},
                          {"eval_case_id": "c2", "pair_id": "p1", "arm": BASELINE}])


# ------------------------------------------------------------------ feeding the conditions

def test_comparisons_feed_matched_pairs_in_the_expected_direction():
    c = compare("p1", {BASELINE: arm(n1=3), VARIANT: arm(n1=2)})
    out = as_matched_pairs([c])
    assert out == [{"pair_id": "p1", "node_id": "n1", "clean": 3.0, "errored": 2.0}]

    from evals.stop_conditions import Threshold, matched_pairs
    f = matched_pairs(out, Threshold(0.0, agreed_by="T", agreed_on="2026-09-07"))
    assert f.verdict == "triggered" and "direction down" in f.detail


def test_comparisons_feed_cohort_invariance_as_two_observations():
    """Not as a pre-computed delta. The condition measures spread itself; handing it a delta would
    move that judgment into the comparison module, where it would be invisible."""
    c = compare("p1", {BASELINE: arm(n1=3), VARIANT: arm(n1=2)})
    out = as_cohort_arms([c])
    assert len(out) == 2
    assert {o["cohort"] for o in out} == {BASELINE, VARIANT}
    assert all(o["artifact_key"] == "p1" for o in out)

    from evals.stop_conditions import Threshold, cohort_invariance
    f = cohort_invariance(out, Threshold(0.0, agreed_by="T", agreed_on="2026-09-07"))
    assert f.verdict == "triggered" and f.observed == 1


def test_an_unscored_criterion_reaches_neither_condition():
    """Both conditions read levels. An abstention has none, and passing it through as a zero would
    be the same lie in two places."""
    c = compare("p1", {BASELINE: arm(n1=None), VARIANT: arm(n1=None)})
    assert as_matched_pairs([c]) == []
    assert as_cohort_arms([c]) == []
