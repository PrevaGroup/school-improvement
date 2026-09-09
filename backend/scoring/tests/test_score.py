"""What stage C and stage D are allowed to see, and what an outcome is allowed to say.

Most of this file asserts ABSENCES, which is deliberate. "One criterion per call", "no cohort",
"no prior scores", "no full text at stage D" are properties of what goes into the context, and a
property of the context can be checked. The alternative is to instruct the model and hope, which
is not a control.

The rater is scripted. No API key, no network, no dollar — which is why these can run on every
commit rather than once before a demo.
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace

import pytest

from scoring.escalate import Policy
from scoring.rater import RaterIdentity, Usage
from scoring.score import (Criterion, build_score_prompt, is_non_attempt, score_artifact,
                           score_criterion)

# The resolved default policy. Part of the rater identity, because the harness — models,
# prompts, normalisation, and how deep it may look — IS the rater.
DEFAULT_ESCALATION = Policy().as_dict()

TEXT = (
    "The Court held that student speech may be limited when it disrupts school. "
    "Tinker set the standard that schools must show substantial disruption. "
    "A DISTINCTIVE UNPROPOSED SENTENCE APPEARS ONLY HERE AND IN NO SPAN. "
    "Later cases narrowed this in ways that are still argued about today."
)

IDENTITY = RaterIdentity("cfg-test", "claude-opus-5", "high", {}, "1", DEFAULT_ESCALATION)


def criterion(node_id="n1", label="use of evidence", cats=(1, 2, 3, 4)):
    return Criterion(node_id=node_id, criterion_label=label, categories=list(cats),
                     descriptors={str(c): f"level {c} descriptor" for c in cats},
                     node_version_id=f"{node_id}-v1")


class FakeRater:
    """Scripted, and it records every prompt it was handed — which is what the absence tests read."""

    def __init__(self, spans_by_node=None, scores_by_node=None):
        self.identity = IDENTITY
        self.spans_by_node = spans_by_node or {}
        self.scores_by_node = scores_by_node or {}
        self.evidence_prompts: list[str] = []
        self.score_prompts: list[str] = []
        self._n = 0

    def propose_spans(self, prompt):
        self.evidence_prompts.append(prompt)
        self._n += 1
        return list(self.spans_by_node.get(self._key(prompt), [])), Usage(1, 10, 5)

    def assign_level(self, prompt):
        self.score_prompts.append(prompt)
        return dict(self.scores_by_node.get(self._key(prompt),
                                            {"level": 3, "abstain": False,
                                             "confidence": "high", "reason": "because"})), \
            Usage(1, 8, 4)

    @staticmethod
    def _key(prompt):
        """The criterion label is in the prompt; scripting by label keeps the fake honest about
        the fact that it only ever sees one criterion at a time."""
        return prompt.split("CRITERION: ", 1)[1].split("\n", 1)[0].strip()


# ------------------------------------------------------------------ outcomes


def test_a_verified_span_produces_a_scored_outcome():
    r = FakeRater({"use of evidence": ["Tinker set the standard"]})
    out, usage = score_criterion(TEXT, criterion(), r)
    assert (out.status, out.level, out.confidence) == ("scored", 3.0, "high")
    assert usage.calls == 2
    assert out.evidence["kept"][0]["span"] == "Tinker set the standard"


def test_a_fabricated_span_is_dropped_and_the_criterion_carries_no_number():
    """The single largest error reduction in the pipeline, and it is string matching."""
    r = FakeRater({"use of evidence": ["The Court explicitly overruled Tinker in 1994"]})
    out, usage = score_criterion(TEXT, criterion(), r)
    assert out.status == "no_verified_evidence"
    assert out.level is None
    assert out.reason_code == "all_spans_unverified"
    assert usage.calls == 1, "stage D must not be paid for when there is nothing to judge"
    assert len(out.evidence["dropped"]) == 1


def test_no_spans_proposed_is_recorded_differently_from_spans_that_failed():
    """`the writing offers nothing here` and `the model made something up` are different failures
    with different fixes, and one reason code cannot carry both."""
    r = FakeRater({"use of evidence": []})
    out, _ = score_criterion(TEXT, criterion(), r)
    assert out.status == "no_verified_evidence"
    assert out.reason_code == "no_spans_proposed"


def test_an_abstention_carries_no_level_even_when_the_model_returns_one():
    r = FakeRater({"use of evidence": ["Tinker set the standard"]},
                  {"use of evidence": {"level": 2, "abstain": True,
                                       "confidence": "low", "reason": "cannot tell"}})
    out, _ = score_criterion(TEXT, criterion(), r)
    assert (out.status, out.level, out.reason_code) == ("abstained", None, "model_abstained")


def test_a_level_that_is_not_on_the_scale_is_an_abstention_not_a_rounding_problem():
    """3.5 on a four-point scale is not a near miss. It is a rater that was not scoring this node,
    and rounding it puts a number nobody assigned into a growth claim."""
    r = FakeRater({"use of evidence": ["Tinker set the standard"]},
                  {"use of evidence": {"level": 3.5, "abstain": False,
                                       "confidence": "high", "reason": "between"}})
    out, _ = score_criterion(TEXT, criterion(), r)
    assert (out.status, out.level, out.reason_code) == ("abstained", None, "off_scale_level")


def test_a_half_point_scale_accepts_its_own_half_points():
    """The same check must not reject a node whose scale genuinely has them — the scale is the
    node's identity, not a global assumption about integers."""
    c = criterion(cats=(1, 1.5, 2, 2.5, 3))
    r = FakeRater({"use of evidence": ["Tinker set the standard"]},
                  {"use of evidence": {"level": 2.5, "abstain": False,
                                       "confidence": "high", "reason": "ok"}})
    out, _ = score_criterion(TEXT, c, r)
    assert (out.status, out.level) == ("scored", 2.5)


def test_a_missing_level_without_an_abstention_still_routes_to_a_human():
    r = FakeRater({"use of evidence": ["Tinker set the standard"]},
                  {"use of evidence": {"level": None, "abstain": False,
                                       "confidence": "low", "reason": "?"}})
    out, _ = score_criterion(TEXT, criterion(), r)
    assert (out.status, out.reason_code) == ("abstained", "no_level_returned")


# ------------------------------------------------------------------ the absences


def test_stage_d_never_sees_the_students_text():
    """Settled by an A/B probe, not by preference: giving stage D the full text moved 5 of 12
    scores, all downward and non-uniformly across traits. A severity shift that lands unevenly is
    a change in what is measured."""
    r = FakeRater({"use of evidence": ["Tinker set the standard"]})
    score_criterion(TEXT, criterion(), r)
    assert "A DISTINCTIVE UNPROPOSED SENTENCE" not in r.score_prompts[0]
    assert "The Court held that student speech" not in r.score_prompts[0]


def test_stage_d_sees_the_kept_spans_and_not_the_dropped_ones():
    r = FakeRater({"use of evidence": ["Tinker set the standard",
                                       "The Court explicitly overruled Tinker in 1994"]})
    score_criterion(TEXT, criterion(), r)
    assert "Tinker set the standard" in r.score_prompts[0]
    assert "explicitly overruled" not in r.score_prompts[0]


def test_build_score_prompt_cannot_be_handed_the_text_at_all():
    """Not a wording rule — the function has no parameter for it, so a later edit cannot leak the
    text into stage D without changing the signature, which is a review-visible act."""
    import inspect
    params = set(inspect.signature(build_score_prompt).parameters)
    assert params == {"criterion", "kept"}


def test_no_call_holds_more_than_one_criterion():
    """A single call emitting every row bakes in halo before any scoring happens."""
    cs = [criterion("n1", "use of evidence"), criterion("n2", "organisation")]
    r = FakeRater({"use of evidence": ["Tinker set the standard"],
                   "organisation": ["Later cases narrowed this"]})
    score_artifact(TEXT, cs, r)
    for prompt in r.evidence_prompts + r.score_prompts:
        assert prompt.count("CRITERION: ") == 1
        assert not ("use of evidence" in prompt and "organisation" in prompt)


def test_no_prior_score_reaches_a_later_call():
    """Nothing accumulates between criteria but the token count."""
    cs = [criterion("n1", "use of evidence"), criterion("n2", "organisation")]
    r = FakeRater({"use of evidence": ["Tinker set the standard"],
                   "organisation": ["Later cases narrowed this"]},
                  {"use of evidence": {"level": 4, "abstain": False,
                                       "confidence": "high", "reason": "SENTINEL RATIONALE"}})
    score_artifact(TEXT, cs, r)
    later = r.evidence_prompts[1] + r.score_prompts[1]
    assert "SENTINEL RATIONALE" not in later
    assert "Level 4:" in later, "the scale is in the prompt; only the prior SCORE must not be"


def test_no_other_students_work_is_in_the_context():
    """A call that holds the cohort makes the scale norm-referenced without anyone deciding to."""
    r = FakeRater({"use of evidence": ["Tinker set the standard"]})
    score_criterion(TEXT, criterion(), r)
    assert r.evidence_prompts[0].count("<text>") == 1


# ------------------------------------------------------------------ the whole artifact


def test_an_empty_document_is_not_scorable_and_costs_nothing():
    cs = [criterion("n1", "use of evidence"), criterion("n2", "organisation")]
    r = FakeRater()
    outs, usage = score_artifact("   \n\t  ", cs, r)
    assert [o.status for o in outs] == ["not_scorable", "not_scorable"]
    assert all(o.level is None for o in outs)
    assert usage.calls == 0
    assert r.evidence_prompts == []


@pytest.mark.parametrize("body", ["Short.", "I dont know", "a"])
def test_short_work_is_scored_not_reclassified(body):
    """A word-count threshold for `not scorable` would remove exactly the students whose scores
    this system exists to be careful about."""
    assert not is_non_attempt(body)


def test_every_criterion_gets_an_outcome_and_usage_is_the_sum():
    cs = [criterion("n1", "use of evidence"), criterion("n2", "organisation"),
          criterion("n3", "clarity")]
    r = FakeRater({"use of evidence": ["Tinker set the standard"],
                   "organisation": ["Later cases narrowed this"]})   # clarity proposes nothing
    outs, usage = score_artifact(TEXT, cs, r)
    assert [o.node_id for o in outs] == ["n1", "n2", "n3"]
    assert [o.status for o in outs] == ["scored", "scored", "no_verified_evidence"]
    assert usage.calls == 5, "two calls each for the scored pair, one for the unscorable one"


# ------------------------------------------------------------------ concurrent criteria

class _SlowRater:
    """Answers criteria out of order on purpose, and records the overlap.

    The first criterion asked is answered LAST. If anything downstream depends on completion
    order, this is the rater that exposes it — a sequential loop cannot produce the interleaving.
    """

    def __init__(self, criteria_count: int, span="the cat sat"):
        self.span = span
        self.n = criteria_count
        self._lock = threading.Lock()
        self.peak = 0
        self._live = 0
        self.order = []
        self._seen = 0

    def _enter(self):
        with self._lock:
            self._live += 1
            self.peak = max(self.peak, self._live)
            mine = self._seen
            self._seen += 1
        # Earlier criteria sleep longer, so they finish last.
        time.sleep(0.05 * (self.n - mine))
        with self._lock:
            self._live -= 1
            self.order.append(mine)

    def propose_spans(self, prompt):
        self._enter()
        return [self.span], Usage(1, 10, 5)

    def assign_level(self, prompt):
        return {"level": 3, "confidence": "high", "reason": "r"}, Usage(1, 10, 5)


def _criteria(n):
    return [criterion(node_id=f"n{i}", label=f"criterion {i}") for i in range(n)]


def test_outcomes_come_back_in_criteria_order_however_the_calls_finish():
    """The one that would be silent. `event_rows` pairs outcomes with criteria positionally, so a
    scrambled list attaches every score to the wrong trait — and the result reads as a terrible
    rater rather than as a bug."""
    crit = _criteria(6)
    rater = _SlowRater(6)
    outcomes, _ = score_artifact("the cat sat on the mat", crit, rater, concurrency=6)
    assert [o.node_id for o in outcomes] == [c.node_id for c in crit]
    # The rater really did answer out of order, or this proves nothing.
    assert rater.order != sorted(rater.order)


def test_the_criteria_are_actually_in_flight_together():
    """A `concurrency=8` that quietly ran sequentially would pass every other test here and take
    six hours in production."""
    rater = _SlowRater(4)
    score_artifact("the cat sat on the mat", _criteria(4), rater, concurrency=4)
    assert rater.peak > 1


def test_concurrency_one_is_the_sequential_path():
    """Kept as an argument rather than deleted: it is what a rate limit gets dialled down to, and
    what a confusing result gets reproduced under."""
    rater = _SlowRater(3)
    outcomes, usage = score_artifact("the cat sat on the mat", _criteria(3), rater, concurrency=1)
    assert rater.peak == 1
    assert [o.level for o in outcomes] == [3, 3, 3]
    assert usage.calls == 6


def test_the_token_count_is_the_same_whatever_the_order():
    """Usage is summed at the end, and addition does not care who finished first."""
    seq, _ = score_artifact("the cat sat on the mat", _criteria(5), _SlowRater(5), concurrency=1)
    con, _ = score_artifact("the cat sat on the mat", _criteria(5), _SlowRater(5), concurrency=5)
    assert [(o.node_id, o.level) for o in seq] == [(o.node_id, o.level) for o in con]


class _FailingRater(_SlowRater):
    def propose_spans(self, prompt):
        self._enter()
        if "criterion 2" in prompt:
            raise RuntimeError("the model refused")
        return [self.span], Usage(1, 10, 5)


def test_a_failure_in_one_criterion_still_fails_the_artifact():
    """It must not be swallowed into a partial result. A paper scored on six of eight traits,
    written and moved to `scored`, would never be picked up again — the missing two would just be
    absent, which is indistinguishable from a trait set that never had them."""
    with pytest.raises(RuntimeError, match="the model refused"):
        score_artifact("the cat sat on the mat", _criteria(4), _FailingRater(4), concurrency=4)


def test_an_empty_document_still_makes_no_calls():
    """The short-circuit is before the pool. Spinning up eight threads to not call anything would
    be harmless and would also mean the check had moved."""
    rater = _SlowRater(3)
    outcomes, usage = score_artifact("", _criteria(3), rater, concurrency=8)
    assert usage.calls == 0
    assert rater.peak == 0
    assert all(o.status == "not_scorable" for o in outcomes)


def test_one_criterion_does_not_open_a_pool():
    rater = _SlowRater(1)
    score_artifact("the cat sat on the mat", _criteria(1), rater, concurrency=8)
    assert rater.peak == 1


# ------------------------------------------------------------------ stage D, cumulative

from scoring.score import (DEFAULT_THRESHOLD, build_band_prompt,  # noqa: E402
                           level_from, score_criterion_cumulative)

SIX = (1, 2, 3, 4, 5, 6)


def test_the_band_is_the_top_of_an_unbroken_ladder():
    """A paper is at band k if it cleared every band up to k. Not the highest band that happened
    to clear — see the incoherence test below for why that distinction is the whole design."""
    d = level_from({2: 0.9, 3: 0.8, 4: 0.7, 5: 0.2, 6: 0.1}, SIX, 0.5)
    assert d["level"] == 4.0
    assert d["decided_at"] == 5.0 and d["decided_p"] == 0.2


def test_an_incoherent_high_band_does_not_promote():
    """"Meets or exceeds 6" cannot be true while "meets or exceeds 4" is false. The ladder rule
    makes a contradiction harmless instead of a promotion — and counts it, because a rater whose
    bands contradict each other is a fact worth having."""
    d = level_from({2: 0.9, 3: 0.8, 4: 0.2, 5: 0.1, 6: 0.99}, SIX, 0.5)
    assert d["level"] == 3.0
    assert d["monotonicity_violations"] == 1


def test_both_ends_of_the_scale_are_reachable():
    """The failure this exists to fix. The category form awarded ZERO 6s across 334 papers and
    used 17% of the range the humans used; a scoring rule that cannot reach its own extremes is
    not a scale."""
    assert level_from({b: 0.99 for b in SIX[1:]}, SIX, 0.5)["level"] == 6.0
    assert level_from({b: 0.01 for b in SIX[1:]}, SIX, 0.5)["level"] == 1.0


def test_the_bottom_band_is_never_asked_about():
    """P(meets or exceeds the lowest band) is 1 by construction. Asking spends a call on a known
    answer, and a model that said 0.3 to it would be answering a different question."""
    d = level_from({2: 0.2}, (1, 2, 3), 0.5)
    assert d["level"] == 1.0
    assert "1" not in d["probabilities"]


def test_a_band_nobody_answered_stops_the_ladder():
    """A missing answer is not a pass. Treating absence as clearance would promote on silence."""
    d = level_from({2: 0.9, 4: 0.9, 5: 0.9, 6: 0.9}, SIX, 0.5)
    assert d["level"] == 2.0
    assert d["decided_at"] == 3.0 and d["decided_p"] is None
    assert d["confidence"] == "low"


def test_confidence_comes_from_the_margin_at_the_deciding_band():
    """A band that landed on 0.51 against a threshold of 0.5 was decided by a coin flip. The level
    still stands — it is the best reading of the evidence — and the teacher deciding how hard to
    look is exactly who this field is for."""
    assert level_from({2: 0.9, 3: 0.51}, SIX, 0.5)["confidence"] == "low"
    assert level_from({2: 0.9, 3: 0.36}, SIX, 0.5)["confidence"] == "medium"
    assert level_from({2: 0.9, 3: 0.05}, SIX, 0.5)["confidence"] == "high"


def test_the_threshold_moves_the_band():
    """It is a parameter of the rater, not a constant, which is why it is in the identity hash."""
    probs = {2: 0.9, 3: 0.7, 4: 0.6, 5: 0.4, 6: 0.2}
    assert level_from(probs, SIX, 0.5)["level"] == 4.0
    assert level_from(probs, SIX, 0.65)["level"] == 3.0
    assert level_from(probs, SIX, 0.95)["level"] == 1.0


def test_one_band_prompt_shows_one_descriptor():
    """Showing the whole scale is what makes the category form a gestalt. A model that can see
    band 6 while judging band 3 is comparing, and comparison is where the middle comes from."""
    c = criterion(cats=(1, 2, 3, 4))
    p = build_band_prompt(c, [{"span": "a verified sentence"}], 3)
    assert "level 3 descriptor" in p
    for other in ("level 1 descriptor", "level 2 descriptor", "level 4 descriptor"):
        assert other not in p
    assert "a verified sentence" in p


# A rater that answers bands IS a cumulative rater, and `score_criterion` dispatches on exactly
# that. Declaring the wrong method here would send the dispatch test down the category path.
CUMULATIVE_IDENTITY = replace(IDENTITY, level_method="cumulative")


class _BandRater:
    """Answers each band from a script keyed by the band number in the prompt."""

    def __init__(self, by_band, spans=("Tinker set the standard",)):
        self.identity = CUMULATIVE_IDENTITY
        self.by_band = by_band
        self.spans = list(spans)
        self.band_prompts = []

    def propose_spans(self, prompt):
        return list(self.spans), Usage(1, 10, 5)

    def judge_band(self, prompt):
        self.band_prompts.append(prompt)
        band = int(prompt.split("THE BAND — level ")[1].split(":")[0])
        return {"probability": self.by_band[band], "reason": f"band {band}"}, Usage(1, 10, 5)


def test_the_cumulative_path_scores_and_records_every_band():
    c = criterion(cats=(1, 2, 3, 4))
    rater = _BandRater({2: 0.9, 3: 0.8, 4: 0.1})
    out, usage = score_criterion_cumulative(TEXT, c, rater,
                                            threshold=DEFAULT_THRESHOLD, concurrency=1)
    assert out.status == "scored" and out.level == 3.0
    # One evidence call plus one per band above the floor.
    assert usage.calls == 4
    assert out.evidence["bands"] == {"2": 0.9, "3": 0.8, "4": 0.1}
    assert out.evidence["threshold"] == DEFAULT_THRESHOLD


def test_no_verified_evidence_still_abstains_before_any_band_is_asked():
    """Abstention is an outcome, not a low score — and paying for five band questions about an
    empty evidence list would be paying to not find out."""
    c = criterion(cats=(1, 2, 3, 4))
    rater = _BandRater({2: 0.9}, spans=("a sentence that is not in the paper",))
    out, usage = score_criterion_cumulative(TEXT, c, rater, concurrency=1)
    assert out.status == "no_verified_evidence" and out.level is None
    assert usage.calls == 1
    assert rater.band_prompts == []


def test_the_contradiction_is_named_in_the_reason_a_teacher_reads():
    c = criterion(cats=(1, 2, 3, 4))
    out, _ = score_criterion_cumulative(
        TEXT, c, _BandRater({2: 0.9, 3: 0.1, 4: 0.99}), concurrency=1)
    assert out.level == 2.0
    assert "contradicted a lower band" in out.reason


def test_the_bands_of_one_criterion_go_out_together():
    c = criterion(cats=(1, 2, 3, 4, 5, 6))
    rater = _BandRater({b: 0.9 for b in range(2, 7)})
    out, _ = score_criterion_cumulative(TEXT, c, rater, concurrency=5)
    assert out.level == 6.0
    assert len(rater.band_prompts) == 5


def test_the_concurrency_setting_reaches_the_band_calls():
    """It is the one dial for backing off a rate limit, and the band calls are what multiply:
    eight criteria each opening their own pool is up to nineteen requests in flight for one paper,
    not eight. A setting that stops at the criteria level cannot back anything off."""
    c = criterion(cats=(1, 2, 3, 4, 5, 6))
    rater = _BandRater({b: 0.9 for b in range(2, 7)})
    out, _ = score_criterion(TEXT, c, rater, concurrency=1)
    assert len(rater.band_prompts) == 5


def test_score_artifact_passes_its_concurrency_down():
    import inspect

    src = inspect.getsource(score_artifact)
    assert "concurrency=concurrency" in src, "the criteria pool must hand its setting onward"


def test_the_band_schema_has_no_range_keywords():
    """The API refuses them on a number — `For 'number' type, properties maximum, minimum are not
    supported` — and it refuses at request time, so a wave fails on every paper after paying for
    its evidence calls. That is what happened."""
    from scoring.prompts import BAND_SCHEMA

    prop = BAND_SCHEMA["properties"]["probability"]
    assert prop == {"type": "number"}


def test_a_probability_outside_the_range_is_refused_not_clamped():
    """A rater answering 1.4 to "what is the probability" did not answer the question. Clamping to
    1.0 would turn a malfunction into a confident pass at that band and every band below it."""
    from scoring.score import BandOutOfRange

    c = criterion(cats=(1, 2, 3))
    for bad in (1.4, -0.2, None, "high"):
        rater = _BandRater({2: bad, 3: 0.5})
        with pytest.raises(BandOutOfRange):
            score_criterion_cumulative(TEXT, c, rater, concurrency=1)


def test_the_ends_of_the_range_are_allowed():
    """0 and 1 are probabilities. Refusing them would punish the certainty this design is trying
    to make available."""
    c = criterion(cats=(1, 2, 3))
    out, _ = score_criterion_cumulative(TEXT, c, _BandRater({2: 1.0, 3: 0.0}), concurrency=1)
    assert out.level == 2.0


def test_a_failed_band_call_names_which_band_of_which_criterion():
    """The batch loop catches per ARTIFACT, so an unwrapped failure says only that a paper failed
    — not which of its nineteen calls did, nor with what in front of it. A wave that failed on a
    quarter of its papers was undiagnosable without running another one."""
    from scoring.score import BandCallFailed

    class _Boom:
        identity = CUMULATIVE_IDENTITY

        def propose_spans(self, prompt):
            return ["Tinker set the standard"], Usage(1, 10, 5)

        def judge_band(self, prompt):
            raise RuntimeError("Error code: 400 - Invalid request data")

    with pytest.raises(BandCallFailed) as e:
        score_criterion_cumulative(TEXT, criterion(label="use of evidence", cats=(1, 2, 3)),
                                   _Boom(), concurrency=1)

    msg = str(e.value)
    assert "use of evidence" in msg          # which criterion
    assert "band 2" in msg                   # which band
    assert "Invalid request data" in msg     # what the API said
    assert "chars" in msg and "verified span" in msg   # the shape of what was sent


def test_a_band_call_is_retried_and_the_success_is_visible(caplog):
    """A retry that WORKED is the evidence separating a flaky service from a bad request. Silent
    recovery would hide the one fact the diagnosis needs."""
    import logging

    class _FlakyOnce:
        identity = CUMULATIVE_IDENTITY

        def __init__(self):
            self.calls = 0

        def propose_spans(self, prompt):
            return ["Tinker set the standard"], Usage(1, 10, 5)

        def judge_band(self, prompt):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("400 Invalid request data")
            return {"probability": 0.9, "reason": "r"}, Usage(1, 10, 5)

    with caplog.at_level(logging.WARNING):
        out, _ = score_criterion_cumulative(TEXT, criterion(cats=(1, 2)), _FlakyOnce(),
                                            concurrency=1)
    assert out.status == "scored"
    assert any("succeeded on attempt 2" in r.getMessage() for r in caplog.records)
    assert any("attempt 1 failed" in r.getMessage() for r in caplog.records)


def test_a_band_that_fails_every_attempt_still_fails_the_paper():
    """The mitigation is bounded. A request that is genuinely bad must not be retried forever, and
    three identical failures on one band is the evidence that it IS the request."""
    from scoring.score import BandCallFailed

    class _AlwaysBad:
        identity = CUMULATIVE_IDENTITY

        def propose_spans(self, prompt):
            return ["Tinker set the standard"], Usage(1, 10, 5)

        def judge_band(self, prompt):
            raise RuntimeError("400 Invalid request data")

    with pytest.raises(BandCallFailed, match="failed 3 times"):
        score_criterion_cumulative(TEXT, criterion(cats=(1, 2)), _AlwaysBad(), concurrency=1)
