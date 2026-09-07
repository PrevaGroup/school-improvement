"""Escalation: a second, deeper look at a criterion that produced no score.

Design: the expansion plan §6 — "Escalation goes deeper, never wider — on declared deterministic
triggers, with a fixed budget and a declared terminal action. Retrying until the model reports
confidence selects for agreeable answers, and is most active exactly where the measurement is
already weakest."

Every clause of that sentence is a rule here, and the last one is the reason the others exist.

## Deeper, never wider

An escalated pass re-runs the SAME criterion on the SAME paper at higher effort. It does not add
criteria, does not add a second rater, and never puts the cohort in context. "Wider" is how a
retry loop turns into a different measurement instrument halfway through a run.

Deeper means one thing concretely: `effort`. That is what "decoding parameters" resolves to in
this codebase, it is already part of the rater's identity hash, and so an escalated score is
stamped as coming from a rater that is genuinely not the pass-1 rater. `scrutiny_passes` is what
lets measurement separate them.

## Declared deterministic triggers, and the one that is deliberately off

The default triggers are the two outcomes that produced NO LEVEL AT ALL: `abstained` and
`no_verified_evidence`. Escalating those cannot shop for an agreeable answer, because there is no
answer yet to disagree with, and the criterion is otherwise going to a human regardless.

`low_confidence` is implemented and OFF by default, and that is the whole point of the plan's
warning. A criterion the model scored 2 with low confidence, re-asked at higher effort, is a
retry against a standing answer — and the pressure of a retry is toward agreement, not accuracy.
Turning it on is a decision somebody makes in a published configuration with their name on it,
not a default that arrives quietly.

## A fixed budget, spent per artifact

The budget is a number of extra scoring passes per ARTIFACT, not per criterion. Per criterion
looks equivalent and is not: thirteen criteria that all abstain would cost thirteen extra passes
on the one paper where the machine is least able to say anything useful — the plan's "most active
exactly where the measurement is already weakest", turned into a bill.

Which criteria get the budget when there is not enough to go round is DECLARED, not incidental:
they are taken in trait-set order. Not "worst first" and not random, because either would make
the escalation a function of the scores, and an escalation that depends on the scores is a
selection effect on the record.

## A declared terminal action

When the budget is spent, or when an escalated pass produces no level either, the criterion keeps
its unscored outcome and routes to a human. There is no third pass and no fallback to "whatever
the last attempt said". The plan's word for this is terminal, and the honest terminal state for a
criterion nothing could place is the one it already had.

## Why the pass-2 event supersedes the pass-1 event

Both rows survive — `score_event` is append-only — and that pairing is the scrutiny-invariance
evidence Phase 5 needs: the same paper, the same criterion, two scrutiny levels, one comparison.
Supersession is only about which one STANDS. Without it a criterion would show twice in the
console, and every "current score" query in the system would have to learn about scrutiny.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Outcomes that produced no level. Escalating these resolves uncertainty; there is no standing
# answer for a retry to drift toward.
NO_LEVEL = ("abstained", "no_verified_evidence")

# `not_scorable` is deliberately absent. It means a defined non-attempt against the bound task —
# an empty document — and no amount of extra scrutiny finds writing that is not there. Escalating
# it would spend the budget on the one case that is certain.
TRIGGERS = ("abstained", "no_verified_evidence", "low_confidence")

DEFAULT_TRIGGERS = ("abstained", "no_verified_evidence")
DEFAULT_BUDGET = 2          # extra passes per artifact
DEFAULT_EFFORT = "high"     # what "deeper" means, concretely

TERMINAL_ACTION = "route_to_human"


@dataclass(frozen=True)
class Policy:
    """What a scoring configuration declares about escalation.

    Frozen and pure so a run's escalation behaviour is a property of a published configuration
    somebody approved, rather than of whichever constants were in the file that week.
    """
    budget: int = DEFAULT_BUDGET
    triggers: tuple[str, ...] = DEFAULT_TRIGGERS
    escalated_effort: str = DEFAULT_EFFORT
    # Present so the terminal action is stated in the record rather than inferred from the absence
    # of a third pass. There is one value; a second would need a reason, not a flag.
    terminal_action: str = TERMINAL_ACTION

    def __post_init__(self) -> None:
        if self.budget < 0:
            raise ValueError("an escalation budget cannot be negative")
        unknown = set(self.triggers) - set(TRIGGERS)
        if unknown:
            raise ValueError(
                f"unknown escalation trigger(s) {sorted(unknown)}. A trigger has to be declared "
                f"in this module to be deterministic — a configuration cannot invent one, or the "
                f"rule that fired is unrecoverable from the record.")
        if self.terminal_action != TERMINAL_ACTION:
            raise ValueError(
                f"the only terminal action is {TERMINAL_ACTION!r}. Taking the last attempt's "
                f"answer instead would make escalation a way of manufacturing a score.")

    @classmethod
    def from_config(cls, raw: dict | None) -> "Policy":
        """Read the policy off a scoring configuration row. Absent means the default."""
        if not raw:
            return cls()
        return cls(
            budget=int(raw.get("budget", DEFAULT_BUDGET)),
            triggers=tuple(raw.get("triggers") or DEFAULT_TRIGGERS),
            escalated_effort=str(raw.get("escalated_effort") or DEFAULT_EFFORT),
            terminal_action=str(raw.get("terminal_action") or TERMINAL_ACTION))

    def as_dict(self) -> dict:
        return {"budget": self.budget, "triggers": list(self.triggers),
                "escalated_effort": self.escalated_effort,
                "terminal_action": self.terminal_action}


@dataclass
class Plan:
    """Which criteria get a second look, and what is being left alone and why."""
    escalate: list[str] = field(default_factory=list)          # node_ids, in trait-set order
    triggers: dict[str, str] = field(default_factory=dict)     # node_id -> the rule that fired
    unfunded: list[str] = field(default_factory=list)          # triggered, no budget left

    def __bool__(self) -> bool:
        return bool(self.escalate)


def trigger_for(outcome, policy: Policy) -> str | None:
    """The declared rule that fires on this outcome, or None.

    Deterministic by construction: a status comparison and a confidence comparison, both against
    values the outcome already carries. Nothing here asks a model whether it would like another go.
    """
    if outcome.status in NO_LEVEL and outcome.status in policy.triggers:
        return outcome.status
    if ("low_confidence" in policy.triggers
            and outcome.status == "scored"
            and (getattr(outcome, "confidence", None) or "").lower() == "low"):
        return "low_confidence"
    return None


def plan(outcomes: list, policy: Policy) -> Plan:
    """Which criteria to escalate, in trait-set order, up to the budget.

    Trait-set order rather than severity order is the load-bearing choice. Spending the budget on
    "the worst ones first" would make which criteria got a second look a function of the scores
    themselves — a selection effect written into the record, and one that would be invisible
    afterwards because the unescalated criteria look exactly like criteria that never triggered.
    """
    out = Plan()
    for o in outcomes:
        fired = trigger_for(o, policy)
        if not fired:
            continue
        if len(out.escalate) < policy.budget:
            out.escalate.append(o.node_id)
            out.triggers[o.node_id] = fired
        else:
            # Named, not dropped. A criterion that met a declared trigger and got no second look
            # because the money ran out is a different fact from one that never triggered, and the
            # run summary is the only place anybody would ever see it.
            out.unfunded.append(o.node_id)
    return out


def keep(first, second) -> tuple[object, bool]:
    """What stands after an escalated pass, and whether the escalation changed anything.

    The second pass stands unless it produced no level while the first did. That case only arises
    with `low_confidence` escalation, and letting a nothing overwrite a something would mean
    turning the trigger on could DELETE scores — which is not what "a deeper look" means to
    anybody who switched it on.
    """
    if second.status not in NO_LEVEL or first.status in NO_LEVEL:
        return second, True
    return first, False
