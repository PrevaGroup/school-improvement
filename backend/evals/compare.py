"""Paired cases: two arms, one configuration, and the delta between them.

Design: "eval_case gains a kind — mined, seeded, or paired — and the harness gains a comparison
runner that executes both arms under identical configuration and grades the delta against a
tolerance."

Three of the five stop conditions are comparisons rather than measurements:

    cohort invariance      the same paper, scored among different classmates
    matched pairs          the same paper, conventions errors added
    scrutiny invariance    the same paper, at one pass and at two

In each, neither arm means anything alone. A single score of 3 is not evidence of anything; a
score of 3 that becomes a 2 when nothing on the scale changed is the whole finding. So this module
never grades an arm — it pairs them, checks that the pairing is legitimate, and returns deltas.

## Identical configuration is the measurement, not a detail

If the two arms run under different scoring configurations, the delta measures the configuration
change and the manipulation together, and there is no way afterwards to say which. A configuration
version IS a rater; two arms under two raters is two people disagreeing, which is a different
experiment that answers a different question.

So `compare` refuses a pair whose arms carry different `scoring_configuration_id`, rather than
reporting a delta it cannot attribute. That refusal is the point of the function.

## A pair with one arm is not a pass

The failure this most wants to avoid is quiet: an arm that errored, or was never written, leaves
its sibling ungraded and the suite reports nothing wrong. A delta computed against a missing arm
is zero, and zero is the passing answer for every one of these conditions. So an incomplete pair
is an ERROR that names the missing arm, never an absent result.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The two sides of a comparison. Named rather than "a"/"b" because which arm is the manipulated
# one matters to the sign of the delta, and a reader should not have to look it up.
BASELINE = "baseline"
VARIANT = "variant"
ARMS = (BASELINE, VARIANT)


class PairError(Exception):
    """The pair could not be compared, and the reason is what the caller reports."""


@dataclass
class Delta:
    """One criterion's movement between the arms of one pair."""
    pair_id: str
    node_id: str
    baseline: float | None
    variant: float | None
    # None when either arm has no level — an abstention is not a zero, and subtracting from it
    # would turn "we could not place this" into "it did not move".
    delta: float | None
    note: str = ""

    @property
    def moved(self) -> bool:
        return bool(self.delta)


@dataclass
class Comparison:
    pair_id: str
    deltas: list[Delta] = field(default_factory=list)
    config_id: str | None = None

    @property
    def moved(self) -> list[Delta]:
        return [d for d in self.deltas if d.moved]

    @property
    def max_abs_delta(self) -> float:
        return max((abs(d.delta) for d in self.deltas if d.delta is not None), default=0.0)


def _levels(arm: dict) -> dict[str, float | None]:
    """node_id -> level for one arm. `None` for any criterion that produced no level."""
    out: dict[str, float | None] = {}
    for s in arm.get("scores") or []:
        out[s["node_id"]] = (float(s["level"]) if s.get("level") is not None
                             and s.get("status") == "scored" else None)
    return out


def compare(pair_id: str, arms: dict[str, dict]) -> Comparison:
    """Two arms of one pair -> per-criterion deltas.

    `arms` is {"baseline": {...}, "variant": {...}}, each carrying `scoring_configuration_id` and
    a list of `scores` ({"node_id", "status", "level"}).
    """
    missing = [a for a in ARMS if a not in arms or not arms[a]]
    if missing:
        # Named, and an error. A delta against a missing arm is zero, and zero is the passing
        # answer for every condition this feeds.
        raise PairError(
            f"pair {pair_id} is missing its {', '.join(missing)} arm, so there is nothing to "
            f"compare. Reporting no movement here would be a pass produced by an absence.")

    configs = {arms[a].get("scoring_configuration_id") for a in ARMS}
    if len(configs) > 1:
        raise PairError(
            f"pair {pair_id} ran under {len(configs)} scoring configurations {sorted(map(str, configs))}. "
            f"A configuration version is a rater, so this delta would measure the rater change "
            f"and the manipulation together with no way to separate them.")

    base, var = _levels(arms[BASELINE]), _levels(arms[VARIANT])
    nodes = sorted(set(base) | set(var))
    if not nodes:
        raise PairError(f"pair {pair_id} produced no criteria on either arm.")

    out = Comparison(pair_id=pair_id, config_id=next(iter(configs)))
    for node_id in nodes:
        b, v = base.get(node_id), var.get(node_id)
        if b is None or v is None:
            # An abstention on one side is a real finding and not a movement. Recorded with a
            # note rather than dropped, because a criterion that stops being scorable when
            # conventions errors are added is itself evidence about the scorer.
            side = ("neither arm" if b is None and v is None
                    else "the baseline" if b is None else "the variant")
            out.deltas.append(Delta(pair_id, node_id, b, v, None,
                                    f"no level on {side}; not counted as movement"))
        else:
            out.deltas.append(Delta(pair_id, node_id, b, v, v - b))
    return out


def pairs_from_cases(cases: list[dict]) -> dict[str, dict[str, dict]]:
    """Group eval cases into pairs by `pair_id`, refusing malformed pairing.

    A case whose `arm` is not one of the two names, or a `pair_id` carrying three arms, is a
    construction error in the suite. Silently keeping two of the three would produce a number.
    """
    grouped: dict[str, dict[str, dict]] = {}
    for c in cases:
        pid, arm = c.get("pair_id"), c.get("arm")
        if not pid:
            continue
        if arm not in ARMS:
            raise PairError(
                f"case {c.get('eval_case_id')} in pair {pid} has arm {arm!r}; the arms are "
                f"{ARMS}. An unnamed arm cannot be placed on either side of a delta.")
        if arm in grouped.setdefault(pid, {}):
            raise PairError(f"pair {pid} has two {arm} arms. A pair has one of each.")
        grouped[pid][arm] = c
    return grouped


# ------------------------------------------------------------------ feeding the conditions


def as_matched_pairs(comparisons: list[Comparison]) -> list[dict]:
    """Comparisons -> the shape `stop_conditions.matched_pairs` reads.

    `clean` is the baseline and `errored` is the variant, which is the direction the condition's
    sign convention assumes: a scorer marking errored prose down produces a negative delta.
    """
    return [{"pair_id": d.pair_id, "node_id": d.node_id,
             "clean": d.baseline, "errored": d.variant}
            for c in comparisons for d in c.deltas if d.delta is not None]


def as_cohort_arms(comparisons: list[Comparison]) -> list[dict]:
    """Comparisons -> the shape `stop_conditions.cohort_invariance` reads.

    Each arm becomes its own observation keyed on the pair, so the condition sees the same paper
    twice under two cohort labels rather than a pre-computed delta — it measures spread itself,
    and handing it a delta would move that judgment into this module.
    """
    out = []
    for c in comparisons:
        for d in c.deltas:
            for cohort, level in ((BASELINE, d.baseline), (VARIANT, d.variant)):
                if level is not None:
                    out.append({"artifact_key": d.pair_id, "node_id": d.node_id,
                                "cohort": cohort, "level": level})
    return out
