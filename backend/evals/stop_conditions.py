"""The five results that mean the system stops releasing scores to students.

Design: the expansion plan §9 — "Five results would mean the system should stop releasing scores
to students while they are true. None is a reason to abandon the approach; each needs a threshold
agreed in advance and a grader that enforces it, because a result without a prior commitment gets
explained rather than acted on."

That last clause is the whole design of this module, and it is enforced rather than described.

## A threshold nobody committed to cannot gate

`Threshold` requires `agreed_by` and `agreed_on`. A condition whose threshold has neither is
still COMPUTED and REPORTED, and cannot return `triggered` — it returns `uncommitted`. The number
is visible, the finding is visible, and the gate stays open.

That asymmetry is deliberate and it is not a safety valve. The failure this prevents is the one
the plan names: a number arrives, somebody decides after the fact what it should have meant, and
the system keeps running. Making an uncommitted threshold unable to STOP anything means the only
way to get a gate is to agree a number first — and the report says, every time, that nobody has.

It also means this module can never silently start blocking releases because a default was
plausible. Defaults here are proposals with a place to sign, not settings.

## Why each condition is a stop rather than a warning

Each one invalidates a specific claim the product makes:

1. COHORT INVARIANCE. The same paper must score the same regardless of what else was in the run.
   Every architectural precaution — one criterion per call, one student per call, no cohort in
   context — exists to make this structurally true, so a failure means an isolation guarantee is
   leaking somewhere none of those precautions can see.

2. SURFACE-FEATURE MATCHED PAIRS. Two papers differing only in conventions errors must score
   identically, because conventions is not in the trait set. A non-zero delta means the scorer is
   reading a construct nobody put on the scale — and the plan flags this as the case most likely
   to fail and the one that falls hardest on multilingual writers.

3. SEVERITY UNIFORMITY ACROSS CRITERIA. If the model is much harsher on one criterion than
   another, the class trait profile — "your class is weakest at counterclaim" — is a statement
   about the rater, not the writers. This condition specifically disqualifies the most robust
   teacher-facing output the design otherwise offers, which is why it stops rather than warns.

4. SUBGROUP ABSTENTION. A sharp rise in "we could not place this" for one subgroup is a fairness
   finding: those students get less feedback, from the same system, for reasons that are about
   the system. The plan is explicit that this is "not one to be managed by lowering the
   threshold", so `abstention_subgroup` deliberately has no knob that makes it easier to pass.

5. TEACHER ACCEPTANCE IS UNINFORMATIVE. If overrides are flat across criteria, seeded probes go
   unnoticed, and drafted feedback is released verbatim at scale, then the human review that
   licenses everything downstream is not happening. The scores may be fine; the evidence that
   anyone checked is absent, and that evidence is what "a teacher approved this" is worth.

## What this module does not do

No thresholds are chosen here, no data is fetched here, and nothing is graded on a schedule here.
Pure functions over observations a caller supplies, so every one of them can be exercised on
constructed inputs — which is what the plan means by "cohort invariance, surface-feature matched
pairs, and scrutiny invariance all need constructed inputs rather than real ones; a real student's
paper is the wrong instrument for every one of them."
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

# What a condition can say. `uncommitted` is not a third kind of pass — it means the question was
# asked, an answer was computed, and nobody has said what the answer would mean.
HOLDS = "holds"                # measured, within the agreed threshold
TRIGGERED = "triggered"        # measured, past the agreed threshold: stop releasing
UNCOMMITTED = "uncommitted"    # measured, and no threshold has been agreed
INSUFFICIENT = "insufficient"  # not enough observations to say anything


@dataclass(frozen=True)
class Threshold:
    """A number somebody agreed to, in advance, with their name on it.

    `agreed_by` and `agreed_on` are not metadata. A threshold without them cannot trigger a stop,
    because the entire point of pre-commitment is that the number existed before the result did.
    """
    value: float
    agreed_by: str = ""
    agreed_on: str = ""          # ISO date
    rationale: str = ""

    @property
    def committed(self) -> bool:
        return bool(self.agreed_by.strip() and self.agreed_on.strip())


@dataclass
class Finding:
    """One condition, measured."""
    name: str
    verdict: str
    observed: float | None
    threshold: Threshold
    detail: str
    # What the reader needs to judge the number themselves, rather than take it on trust.
    n: int = 0
    breakdown: dict = field(default_factory=dict)

    @property
    def stops_release(self) -> bool:
        return self.verdict == TRIGGERED


def _finding(name: str, observed: float | None, t: Threshold, detail: str, *,
             worse_is_higher: bool = True, n: int = 0, breakdown: dict | None = None) -> Finding:
    """Turn a measurement into a verdict, with the pre-commitment rule applied last.

    The order matters: measure, then decide whether anybody is allowed to act on it. Reversing
    them would mean an uncommitted threshold suppressed the measurement too, and the number a
    person needs in order to agree a threshold is exactly the number they would stop seeing.
    """
    if observed is None:
        return Finding(name, INSUFFICIENT, None, t, detail, n, breakdown or {})
    past = observed > t.value if worse_is_higher else observed < t.value
    if not t.committed:
        return Finding(
            name, UNCOMMITTED, observed, t,
            f"{detail} No threshold has been agreed, so this cannot stop a release. "
            f"The proposed value is {t.value:g} and this run would "
            f"{'exceed' if past else 'be within'} it.", n, breakdown or {})
    return Finding(name, TRIGGERED if past else HOLDS, observed, t, detail, n, breakdown or {})


# ------------------------------------------------------------------ 1. cohort invariance

def cohort_invariance(arms: list[dict], t: Threshold) -> Finding:
    """The same paper, scored in different company, must get the same level.

    `arms` is a list of {"artifact_key": str, "node_id": str, "cohort": str, "level": float}. Each
    artifact_key × node_id should appear in two or more cohorts; the measure is the largest spread
    of levels for any one of them.

    A failure here is more serious than its size suggests. Nothing in the pipeline shows the
    scorer another student's work — one student per call, no cohort in context — so a moving score
    means an isolation guarantee is leaking through a path none of those precautions can see.
    """
    by_key: dict[tuple[str, str], list[float]] = {}
    for a in arms:
        if a.get("level") is None:
            continue
        by_key.setdefault((a["artifact_key"], a["node_id"]), []).append(float(a["level"]))

    spreads = {f"{k[0]}/{k[1]}": max(v) - min(v) for k, v in by_key.items() if len(v) > 1}
    if not spreads:
        return _finding("cohort_invariance", None, t,
                        "No paper was scored in more than one cohort, so invariance was not "
                        "tested. This is not a pass.")
    worst = max(spreads.values())
    moved = {k: v for k, v in spreads.items() if v > 0}
    return _finding(
        "cohort_invariance", worst, t,
        f"{len(moved)} of {len(spreads)} paper-criterion pairs moved when the cohort changed; "
        f"the largest movement was {worst:g} of a scale point.",
        n=len(spreads), breakdown=dict(sorted(moved.items(), key=lambda kv: -kv[1])[:10]))


# ------------------------------------------------------------------ 2. matched pairs

def matched_pairs(pairs: list[dict], t: Threshold) -> Finding:
    """Two papers differing only in conventions must score identically.

    `pairs` is a list of {"pair_id": str, "node_id": str, "clean": float, "errored": float}.

    The expected delta is EXACTLY ZERO, not "small". Conventions is not in the trait set, so any
    movement is the scorer reading a construct nobody put on the scale. The plan calls this the
    case most likely to fail and the one that falls hardest on multilingual writers, which is why
    the reported number is the mean absolute delta AND the count of pairs that moved at all — a
    mean can hide a few large movements behind many zeros.
    """
    deltas, moved = [], {}
    for p in pairs:
        if p.get("clean") is None or p.get("errored") is None:
            continue
        d = float(p["errored"]) - float(p["clean"])
        deltas.append(abs(d))
        if d != 0:
            moved[f"{p['pair_id']}/{p['node_id']}"] = d
    if not deltas:
        return _finding("matched_pairs", None, t,
                        "No matched pairs were scored, so the conventions leak was not tested. "
                        "This is not a pass.")
    mean_abs = statistics.fmean(deltas)
    # Direction matters and is worth surfacing: a scorer that marks errored prose DOWN is
    # penalising conventions, which is the failure. One that marks it UP is stranger and worse.
    signed = [v for v in moved.values()]
    direction = ("down" if signed and statistics.fmean(signed) < 0 else
                 "up" if signed else "none")
    return _finding(
        "matched_pairs", mean_abs, t,
        f"{len(moved)} of {len(deltas)} matched pairs moved when only conventions changed "
        f"(mean absolute movement {mean_abs:.3f} scale points, direction {direction}). The "
        f"expected movement is exactly zero: conventions is not on this scale.",
        n=len(deltas), breakdown=dict(sorted(moved.items(), key=lambda kv: -abs(kv[1]))[:10]))


# ------------------------------------------------------------------ 3. severity uniformity

def severity_uniformity(observations: list[dict], t: Threshold) -> Finding:
    """Is the model much harsher on some criteria than others?

    `observations` is a list of {"node_id": str, "model": float, "human": float} over an
    anchor set — papers with expert scores. Severity per criterion is the mean signed difference
    between the model and the humans; the measure is the SPREAD of those severities.

    Uniform severity is survivable: every score is shifted the same way and comparisons within a
    class still hold. Non-uniform severity is not, and it specifically disqualifies the class
    trait profile — "your class is weakest at counterclaim" becomes a statement about the rater.
    That is the most robust teacher-facing output the design otherwise offers, which is why this
    stops rather than warns.

    Note what this needs: HUMAN scores. Without an anchor set there is no severity to estimate,
    and the honest answer is `insufficient` rather than a number computed from the model alone.
    """
    by_node: dict[str, list[float]] = {}
    for o in observations:
        if o.get("model") is None or o.get("human") is None:
            continue
        by_node.setdefault(o["node_id"], []).append(float(o["model"]) - float(o["human"]))

    severities = {k: statistics.fmean(v) for k, v in by_node.items() if v}
    if len(severities) < 2:
        return _finding("severity_uniformity", None, t,
                        "Fewer than two criteria have both model and human scores, so severity "
                        "cannot be compared across criteria. This is not a pass.")
    spread = max(severities.values()) - min(severities.values())
    n = sum(len(v) for v in by_node.values())
    return _finding(
        "severity_uniformity", spread, t,
        f"Model severity ranges from {min(severities.values()):+.2f} to "
        f"{max(severities.values()):+.2f} scale points across {len(severities)} criteria "
        f"(spread {spread:.2f}). A uniform offset is survivable; a spread this is not, because "
        f"the trait profile would report the rater rather than the class.",
        n=n, breakdown={k: round(v, 3) for k, v in sorted(severities.items(),
                                                          key=lambda kv: kv[1])})


# ------------------------------------------------------------------ 4. subgroup abstention

def abstention_subgroup(observations: list[dict], t: Threshold, *,
                        min_per_subgroup: int = 20) -> Finding:
    """Does one subgroup get "we could not place this" much more often than the rest?

    `observations` is a list of {"subgroup": str, "abstained": bool}. The measure is the largest
    gap between any single subgroup's abstention rate and the rate for everyone else.

    A student whose criteria abstain gets less feedback from the same system, for reasons that
    are about the system. The plan is explicit that this is "a fairness finding, and not one to be
    managed by lowering the threshold" — so this function has no knob that makes it easier to
    pass. `min_per_subgroup` suppresses noise from tiny groups and does not move the line.

    Subgroups below the minimum are REPORTED rather than dropped silently. A subgroup too small to
    measure is exactly the one most likely to be underserved, and a report that omitted it would
    read as evidence of fairness.
    """
    groups: dict[str, list[bool]] = {}
    for o in observations:
        groups.setdefault(str(o.get("subgroup") or "unstated"), []).append(bool(o["abstained"]))

    measurable = {g: v for g, v in groups.items() if len(v) >= min_per_subgroup}
    too_small = {g: len(v) for g, v in groups.items() if len(v) < min_per_subgroup}
    if len(measurable) < 2:
        return _finding("abstention_subgroup", None, t,
                        f"Fewer than two subgroups have {min_per_subgroup} or more observations, "
                        f"so no comparison is possible. This is not a pass.",
                        breakdown={"too_small": too_small})

    rates = {g: sum(v) / len(v) for g, v in measurable.items()}
    gaps = {}
    for g in measurable:
        rest = [x for h, v in measurable.items() if h != g for x in v]
        gaps[g] = rates[g] - (sum(rest) / len(rest))
    worst_group = max(gaps, key=lambda g: gaps[g])
    worst = gaps[worst_group]
    return _finding(
        "abstention_subgroup", worst, t,
        f"{worst_group} abstains at {rates[worst_group]:.1%}, which is {worst:+.1%} against "
        f"everyone else. A subgroup that gets less feedback from the same system is a fairness "
        f"finding about the system.",
        n=sum(len(v) for v in measurable.values()),
        breakdown={"rates": {g: round(r, 4) for g, r in sorted(rates.items(),
                                                              key=lambda kv: -kv[1])},
                   "too_small_to_measure": too_small})


# ------------------------------------------------------------------ 5. teacher acceptance

def teacher_acceptance(reviews: list[dict], t: Threshold) -> Finding:
    """Is the human review actually happening, or is it a click?

    `reviews` is a list of {"artifact_id", "node_id", "overridden": bool,
    "feedback_edited": bool, "probe": bool, "probe_caught": bool}.

    Three signals, and the condition triggers on the WORST of them, because each alone is enough
    to mean the review is uninformative:

    * Overrides flat across criteria — a reviewer who disagrees at the same rate everywhere is
      not reading criteria, they are sampling.
    * Seeded probes missed — a deliberately wrong score that was released is direct evidence.
    * Feedback released verbatim at scale — a drafting model nobody edits is a drafting model
      nobody is checking.

    Reported as one number so it can gate, and broken down so it can be understood. A single
    "acceptance score" with no breakdown would be exactly the uninformative summary this
    condition exists to detect.
    """
    if not reviews:
        return _finding("teacher_acceptance", None, t,
                        "No reviews to assess. This is not a pass.")

    by_node: dict[str, list[bool]] = {}
    for r in reviews:
        by_node.setdefault(r["node_id"], []).append(bool(r.get("overridden")))
    override_rates = {k: sum(v) / len(v) for k, v in by_node.items() if v}
    # Flatness: how little the override rate varies between criteria. Population stdev, so one
    # criterion is 0 rather than undefined.
    flatness = (1.0 - min(1.0, statistics.pstdev(list(override_rates.values())) * 4)
                if len(override_rates) > 1 else 1.0)

    probes = [r for r in reviews if r.get("probe")]
    probe_miss = (1.0 - sum(bool(r.get("probe_caught")) for r in probes) / len(probes)
                  if probes else None)

    artifacts = {r["artifact_id"]: r for r in reviews}
    verbatim = (sum(not bool(r.get("feedback_edited")) for r in artifacts.values())
                / len(artifacts)) if artifacts else 0.0

    parts = {"override_flatness": round(flatness, 3),
             "feedback_released_verbatim": round(verbatim, 3),
             "override_rate_by_criterion": {k: round(v, 3) for k, v in override_rates.items()}}
    if probe_miss is None:
        # Named, not scored around. No probes means the strongest of the three signals was never
        # collected, and a score computed from the other two would look like evidence.
        parts["seeded_probes"] = "none were seeded — the strongest signal is missing"
    else:
        parts["seeded_probe_miss_rate"] = round(probe_miss, 3)

    worst = max([flatness, verbatim] + ([probe_miss] if probe_miss is not None else []))
    return _finding(
        "teacher_acceptance", worst, t,
        f"Override flatness {flatness:.2f}, feedback released verbatim {verbatim:.0%}"
        + (f", seeded probes missed {probe_miss:.0%}" if probe_miss is not None
           else ", no seeded probes") +
        ". The scores may be fine; what is in question is whether anybody checked.",
        n=len(reviews), breakdown=parts)


# ------------------------------------------------------------------ the set

# Proposed thresholds, deliberately UNCOMMITTED. Each carries a rationale so the conversation that
# commits it starts from an argument rather than from a blank field. Until somebody fills in
# `agreed_by` and `agreed_on`, every one of these reports and none of them can stop a release.
PROPOSED: dict[str, Threshold] = {
    "cohort_invariance": Threshold(
        0.0, rationale="Exactly zero. Nothing shows the scorer another student's work, so any "
                       "movement at all means an isolation guarantee is leaking."),
    "matched_pairs": Threshold(
        0.0, rationale="Exactly zero. Conventions is not on the scale, so a paper cannot move "
                       "for having errors in it."),
    "severity_uniformity": Threshold(
        0.5, rationale="Half a scale point of spread between the harshest and mildest criterion. "
                       "Beyond that the trait profile reports the rater rather than the class. "
                       "This one is a genuine judgment call and the number is a guess."),
    "abstention_subgroup": Threshold(
        0.10, rationale="Ten percentage points above the rest. Chosen to be noticeable rather "
                        "than defensible — it needs a real argument before it gates."),
    "teacher_acceptance": Threshold(
        0.90, rationale="Any one of the three signals at 90%: overrides essentially flat, or "
                        "nine in ten drafts released unedited, or nine in ten probes missed."),
}

CONDITIONS = {
    "cohort_invariance": cohort_invariance,
    "matched_pairs": matched_pairs,
    "severity_uniformity": severity_uniformity,
    "abstention_subgroup": abstention_subgroup,
    "teacher_acceptance": teacher_acceptance,
}


def evaluate(data: dict, thresholds: dict[str, Threshold] | None = None) -> dict:
    """Every condition that has data, and whether releases should stop.

    A condition with no data is `insufficient`, which is NOT a pass — the summary counts it
    separately, because "we did not test this" and "this held" are the two answers a report like
    this is most often read as interchangeable.
    """
    t = {**PROPOSED, **(thresholds or {})}
    findings = [CONDITIONS[name](data[name], t[name])
                for name in CONDITIONS if name in data]

    return {
        "findings": [f.__dict__ | {"threshold": f.threshold.__dict__} for f in findings],
        "stop_release": any(f.stops_release for f in findings),
        "triggered": [f.name for f in findings if f.verdict == TRIGGERED],
        # The two categories a reader must not confuse with holding.
        "uncommitted": [f.name for f in findings if f.verdict == UNCOMMITTED],
        "insufficient": [f.name for f in findings if f.verdict == INSUFFICIENT],
        "not_run": [n for n in CONDITIONS if n not in data],
        "held": [f.name for f in findings if f.verdict == HOLDS],
    }
