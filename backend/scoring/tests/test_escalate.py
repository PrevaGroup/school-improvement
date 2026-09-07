"""Escalation: a bounded second look, and the ways a second look goes wrong.

The plan's sentence is the specification, and every clause is a failure mode somebody has shipped:

    "Escalation goes deeper, never wider — on declared deterministic triggers, with a fixed budget
    and a declared terminal action. Retrying until the model reports confidence selects for
    agreeable answers, and is most active exactly where the measurement is already weakest."

The last clause is why the rest matter. An unbounded retry loop does not find better scores, it
finds agreeable ones, and it fires hardest on the papers where the machine could say least — which
aims a bias generator at exactly the students the whole subsystem exists to be careful about.
"""
from __future__ import annotations

import pytest

from scoring import escalate
from scoring.escalate import DEFAULT_TRIGGERS, NO_LEVEL, Policy, keep, plan, trigger_for
from scoring.score import Outcome


def out(node_id: str, status: str = "scored", level=3, confidence="high") -> Outcome:
    return Outcome(node_id=node_id, node_version_id=f"{node_id}.v1", status=status,
                   level=level if status == "scored" else None, confidence=confidence)


# ------------------------------------------------------------------ the triggers

def test_the_default_triggers_are_the_outcomes_with_no_level():
    """Escalating an abstention cannot shop for an agreeable answer, because there is no answer
    yet to disagree with — and the criterion is going to a human either way. That is the whole
    difference between resolving uncertainty and manufacturing a score."""
    assert set(DEFAULT_TRIGGERS) == set(NO_LEVEL)
    p = Policy()
    assert trigger_for(out("a", "abstained"), p) == "abstained"
    assert trigger_for(out("b", "no_verified_evidence"), p) == "no_verified_evidence"


def test_a_scored_criterion_is_not_escalated_by_default():
    """Re-asking a standing answer is a retry, and the pressure of a retry is toward agreement."""
    assert trigger_for(out("a", "scored", 2, confidence="low"), Policy()) is None


def test_low_confidence_exists_and_is_off_until_somebody_publishes_it():
    """Implemented so the decision is available; off so it is a decision. Turning it on happens in
    a published configuration with a name and a rationale on it, not by default."""
    assert "low_confidence" in escalate.TRIGGERS
    assert "low_confidence" not in DEFAULT_TRIGGERS
    on = Policy(triggers=("abstained", "low_confidence"))
    assert trigger_for(out("a", "scored", 2, confidence="low"), on) == "low_confidence"
    assert trigger_for(out("a", "scored", 2, confidence="high"), on) is None


def test_a_non_attempt_is_never_escalated():
    """`not_scorable` means an empty document. No amount of extra scrutiny finds writing that is
    not there, and escalating it would spend the budget on the one certain case."""
    assert "not_scorable" not in escalate.TRIGGERS
    for triggers in (DEFAULT_TRIGGERS, escalate.TRIGGERS):
        assert trigger_for(out("a", "not_scorable"), Policy(triggers=tuple(triggers))) is None


def test_a_configuration_cannot_invent_a_trigger():
    """A trigger has to be declared in the module to be deterministic. One that only exists as a
    string in a config row is a rule nobody can reconstruct from the record afterwards."""
    with pytest.raises(ValueError, match="unknown escalation trigger"):
        Policy(triggers=("vibes",))


# ------------------------------------------------------------------ the budget

def test_the_budget_is_spent_per_artifact_not_per_criterion():
    """Thirteen abstaining criteria must not cost thirteen extra passes on the one paper where
    the machine is least able to say anything — the plan's "most active exactly where the
    measurement is already weakest", turned into a bill."""
    outcomes = [out(f"n{i}", "abstained") for i in range(13)]
    p = plan(outcomes, Policy(budget=2))
    assert len(p.escalate) == 2
    assert len(p.unfunded) == 11


def test_the_budget_is_spent_in_trait_set_order():
    """Not worst-first and not random. Either would make which criteria got a second look a
    function of the scores, which is a selection effect written into the record — and an invisible
    one, because an unescalated criterion looks exactly like one that never triggered."""
    outcomes = [out("n1", "scored"), out("n2", "abstained"),
                out("n3", "no_verified_evidence"), out("n4", "abstained")]
    p = plan(outcomes, Policy(budget=2))
    assert p.escalate == ["n2", "n3"]
    assert p.unfunded == ["n4"]


def test_a_criterion_the_budget_could_not_reach_is_named():
    """A criterion that met a declared trigger and got no second look because the money ran out is
    a different fact from one that never triggered. Counting them together loses the distinction
    permanently."""
    p = plan([out(f"n{i}", "abstained") for i in range(4)], Policy(budget=1))
    assert p.unfunded == ["n1", "n2", "n3"]


def test_a_budget_of_zero_escalates_nothing():
    """The off switch, and it must be reachable — next-day grading makes the budget a cost
    decision, and zero is a legitimate answer to it."""
    p = plan([out("n1", "abstained")], Policy(budget=0))
    assert not p and p.unfunded == ["n1"]


def test_a_negative_budget_is_refused_rather_than_treated_as_zero():
    """A typo that quietly disables escalation on a configuration whose author thought they had
    turned it up is the kind of silence this codebase keeps finding."""
    with pytest.raises(ValueError, match="cannot be negative"):
        Policy(budget=-1)


def test_nothing_triggered_costs_nothing():
    assert not plan([out("n1"), out("n2")], Policy())


# ------------------------------------------------------------------ deeper, never wider

def test_deeper_means_effort_which_is_part_of_the_rater_identity():
    """So an escalated score is stamped as coming from a rater that genuinely is not the pass-1
    rater, rather than as the same rater being luckier the second time."""
    from scoring.rater import RaterIdentity

    base = RaterIdentity(config_id="cfg-1", model_id="claude-opus-5", effort="medium",
                         prompt_versions={"evidence": "ev.1"}, normalization_version="n.1")
    deeper = RaterIdentity(config_id="cfg-1", model_id="claude-opus-5",
                           effort=Policy().escalated_effort,
                           prompt_versions={"evidence": "ev.1"}, normalization_version="n.1")
    assert Policy().escalated_effort != base.effort
    assert deeper.definition_hash != base.definition_hash


def test_escalation_never_adds_criteria():
    """Wider is how a retry loop becomes a different measurement instrument halfway through a
    run. Every node in the plan came from the outcomes it was given."""
    outcomes = [out("n1", "abstained"), out("n2")]
    p = plan(outcomes, Policy(budget=5))
    assert set(p.escalate) <= {o.node_id for o in outcomes}


# ------------------------------------------------------------------ the terminal action

def test_the_only_terminal_action_is_routing_to_a_human():
    """Taking the last attempt's answer instead would make escalation a way of manufacturing a
    score out of repeated asking."""
    with pytest.raises(ValueError, match="only terminal action"):
        Policy(terminal_action="take_last")


def test_an_escalated_pass_that_still_finds_nothing_leaves_the_criterion_unscored():
    """The honest terminal state for a criterion nothing could place is the one it already had.
    There is no third pass and no fallback."""
    first = out("n1", "abstained")
    second = out("n1", "no_verified_evidence")
    winner, changed = keep(first, second)
    assert winner.status in NO_LEVEL and changed


def test_a_deeper_look_that_found_nothing_cannot_delete_a_level():
    """Only reachable with `low_confidence` escalation on. If a nothing could overwrite a
    something, switching that trigger on would DELETE scores — which is not what "a deeper look"
    means to anyone who switched it on."""
    first = out("n1", "scored", 2, confidence="low")
    second = out("n1", "abstained")
    winner, changed = keep(first, second)
    assert winner is first and not changed


def test_a_deeper_look_that_produced_a_level_stands():
    first = out("n1", "abstained")
    second = out("n1", "scored", 3)
    winner, changed = keep(first, second)
    assert winner is second and changed


# ------------------------------------------------------------------ the policy is published

def test_an_absent_policy_is_the_default_rather_than_no_escalation():
    """Every configuration written before the column existed has NULL here. Reading that as "no
    escalation" would be a silent behaviour difference between old and new configurations."""
    assert Policy.from_config(None) == Policy()
    assert Policy.from_config({}) == Policy()


def test_a_published_policy_is_read_back_exactly():
    raw = {"budget": 4, "triggers": ["abstained"], "escalated_effort": "high",
           "terminal_action": "route_to_human"}
    p = Policy.from_config(raw)
    assert p.budget == 4 and p.triggers == ("abstained",)
    assert p.as_dict() == raw


def test_the_policy_cannot_be_edited_after_it_is_read():
    """A run's escalation behaviour is a property of a configuration somebody approved, not
    something a later line of code can adjust mid-run."""
    with pytest.raises(Exception):
        Policy().budget = 99   # type: ignore[misc]


# ------------------------------------------------------------------ on the path, not beside it

class TwoPassRater:
    """A rater that abstains at low effort and scores at high — so a test can tell the difference
    between escalation happening and escalation being configured."""

    def __init__(self, identity):
        self.identity = identity
        self.calls: list[str] = []

    def propose_spans(self, prompt):
        from scoring.rater import Usage
        self.calls.append(f"spans:{self.identity.effort}")
        # Exact case: `normalize` folds typography and whitespace and deliberately NOT case,
        # because a scorer shown "the court" where the student wrote "the Court" is being shown
        # something the student did not write.
        return (["The court said"] if self.identity.effort == "high" else []), Usage(calls=1)

    def assign_level(self, prompt):
        from scoring.rater import Usage
        self.calls.append(f"level:{self.identity.effort}")
        return {"level": 3, "confidence": "high", "reason": "on the deeper look"}, Usage(calls=1)

    def write_feedback(self, prompt):  # pragma: no cover - stage E is not on this path
        raise AssertionError("escalation must not reach stage E")


def test_escalation_is_reachable_from_the_scoring_run():
    """The defect this codebase keeps finding is a mechanism that exists, is tested, is green, and
    is on no path. `escalate_pass` is called by `_score_one`; this asserts it does something."""
    from scoring.run_scoring import escalate_pass
    from scoring.rater import RaterIdentity
    from scoring.score import Criterion

    identity = RaterIdentity(config_id="cfg-1", model_id="claude-opus-5", effort="medium",
                             prompt_versions={"e": "1"}, normalization_version="n.1")
    criteria = [Criterion(node_id="n1", criterion_label="Counterclaim", categories=[1, 2, 3, 4],
                          descriptors={"1": "a", "2": "b", "3": "c", "4": "d"},
                          node_version_id="n1.v1")]
    first = [out("n1", "no_verified_evidence")]

    made: list[TwoPassRater] = []

    def factory(ident):
        r = TwoPassRater(ident)
        made.append(r)
        return r

    stands, p, usage, unchanged = escalate_pass(
        "The court said students keep their rights.", criteria, first, Policy(), identity, factory)

    assert p.escalate == ["n1"]
    assert [o.status for o in stands] == ["scored"]
    assert usage.calls > 0
    # Deeper, concretely: the second pass ran at the escalated effort, not the configured one.
    assert made[0].identity.effort == Policy().escalated_effort
    assert all(c.endswith(":high") for c in made[0].calls)


def test_the_escalated_event_supersedes_the_first_pass_and_says_what_fired():
    """Both rows survive — the table is append-only — and the pair is the scrutiny-invariance
    comparison Phase 5 wants. Supersession only decides which one STANDS, so the console does not
    show one criterion twice and no "current score" query has to learn about scrutiny."""
    from scoring.rater import RaterIdentity
    from scoring.run_scoring import ESCALATED_PASS, SCRUTINY_PASS, event_rows

    identity = RaterIdentity(config_id="cfg-1", model_id="claude-opus-5", effort="medium",
                             prompt_versions={"e": "1"}, normalization_version="n.1")
    artifact = {"artifact_id": "art-1", "run_id": "run-1", "student_id": "stu-1",
                "section_id": "sec-1", "task_id": "task-1", "iteration": "final",
                "window_label": "fall 2026", "tenant_id": "public", "visibility": "public"}

    first = event_rows(artifact, [out("n1", "abstained")], identity, "ts.1", True)
    second = event_rows(artifact, [out("n1", "scored", 3)], identity, "ts.1", True,
                        scrutiny_passes=ESCALATED_PASS, triggers={"n1": "abstained"},
                        supersedes={"n1": first[0]["event_id"]})

    assert first[0]["scrutiny_passes"] == SCRUTINY_PASS
    assert first[0]["escalation_trigger"] is None
    assert second[0]["scrutiny_passes"] == ESCALATED_PASS
    assert second[0]["escalation_trigger"] == "abstained"
    assert second[0]["supersedes_event_id"] == first[0]["event_id"]
    # Two administrations of the same rater are two observations, so two idempotency keys. One key
    # would make the second insert a constraint violation and escalation would fail as a duplicate.
    assert first[0]["idempotency_key"] != second[0]["idempotency_key"]


def test_measurement_can_already_separate_the_two_passes():
    """`include_escalated` and the scrutiny bounds have been in `measurement/frames.py` since it
    was written, with nothing to filter. An escalated score comes from a different administration
    of the same rater, so a frame that mixed them without being able to say so would be pooling
    two instruments."""
    from measurement.frames import admits

    esc = {"scrutiny_passes": 2, "escalation_trigger": "abstained"}
    plain = {"scrutiny_passes": 1, "escalation_trigger": None}
    assert admits({"include_escalated": False}, plain)
    assert not admits({"include_escalated": False}, esc)
