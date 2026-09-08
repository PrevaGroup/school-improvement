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

import pytest

from scoring.rater import RaterIdentity, Usage
from scoring.score import (Criterion, build_score_prompt, is_non_attempt, score_artifact,
                           score_criterion)

TEXT = (
    "The Court held that student speech may be limited when it disrupts school. "
    "Tinker set the standard that schools must show substantial disruption. "
    "A DISTINCTIVE UNPROPOSED SENTENCE APPEARS ONLY HERE AND IN NO SPAN. "
    "Later cases narrowed this in ways that are still argued about today."
)

IDENTITY = RaterIdentity("cfg-test", "claude-opus-5", "high", {}, "1")


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
