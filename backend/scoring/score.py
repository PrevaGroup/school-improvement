"""Stage C then stage D — evidence, then a level, one criterion at a time.

Pure. No database, no clock, no ids, no network of its own: a rater is passed in, and everything
here is a function of (text, criteria, rater). That is what lets `tests/test_score.py` assert the
architectural properties — no halo, no cohort, no prior scores, no full text at stage D — against
the assembled prompts, with a scripted fake rater and no API key.

THE ORDER IS THE ARCHITECTURE. Stage C proposes spans from the student's text. The verifier drops
every span that is not an exact substring of it. Stage D sees the survivors and never the text.
That last clause was tested, not assumed: an A/B probe that gave stage D the full text alongside
the verified spans moved 5 of 12 scores, every one of them down, and NON-UNIFORMLY across traits.
A severity shift that lands unevenly on different criteria is a change in what is being measured,
not a refinement of it — so the probe argued against the change it was run to justify, and stage D
still sees spans only.

ABSTENTION IS AN OUTCOME, NOT AN ERROR. A criterion with no verified evidence routes to a human
carrying no number at all. Writing a 1 there would be a claim nobody made, and the difference
between "the writing is weak on this" and "we could not tell" is the difference the whole record
is built to keep.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from dataclasses import dataclass, field

from .prompts import BAND_PROMPT, EVIDENCE_PROMPT, SCORE_PROMPT, render_scale
from .rater import Rater, Usage
from .verify import NORM_VERSION, normalize, verify_all

# Reason codes. Free text explains; a code is what a query can count, and the rate of each of
# these over a run is the signal that something upstream has broken.
NO_VERIFIED_EVIDENCE = "all_spans_unverified"
NO_SPANS_PROPOSED = "no_spans_proposed"
MODEL_ABSTAINED = "model_abstained"
OFF_SCALE = "off_scale_level"
NO_LEVEL_RETURNED = "no_level_returned"
EMPTY_DOCUMENT = "empty_document"


@dataclass(frozen=True)
class Criterion:
    """One node, as the prompt needs it. Assembled by the driver from the registry tables."""
    node_id: str
    criterion_label: str
    categories: list           # the scale — the node's identity, and the only legal levels
    descriptors: dict          # category -> descriptor (a list of clauses stays a list)
    node_version_id: str


@dataclass(frozen=True)
class Outcome:
    """One criterion's result. Maps one-to-one onto a score_event row, and holds no ids of its
    own: minting those is the driver's job, because they are the part that touches the world."""
    node_id: str
    node_version_id: str
    status: str                       # core vocab.SCORE_STATUSES
    level: float | None = None
    confidence: str | None = None
    reason: str | None = None
    reason_code: str | None = None
    evidence: dict = field(default_factory=dict)


def is_non_attempt(text: str) -> bool:
    """Empty after normalization, and nothing else.

    Deliberately not a word-count threshold. A twelve-word response is a low score, and a rule
    that reclassifies short work as unscorable would remove exactly the students whose scores the
    system exists to be careful about. `not_scorable` means "no attempt against the bound task",
    which for a document means there is nothing on the page.
    """
    return not normalize(text)


def build_evidence_prompt(criterion: Criterion, text: str) -> str:
    return EVIDENCE_PROMPT.format(
        name=criterion.criterion_label,
        levels=render_scale(criterion.criterion_label, criterion.descriptors,
                            criterion.categories),
        text=text)


def build_score_prompt(criterion: Criterion, kept: list[dict]) -> str:
    """Verified spans only. The student's text is not a parameter of this function, which is the
    cheapest possible way to make sure it cannot leak into stage D by a later edit."""
    return SCORE_PROMPT.format(
        name=criterion.criterion_label,
        levels=render_scale(criterion.criterion_label, criterion.descriptors,
                            criterion.categories),
        evidence="\n".join('{}. "{}"'.format(i + 1, k["span"]) for i, k in enumerate(kept)))


DEFAULT_THRESHOLD = 0.5

# A band whose probability sits this close to the threshold was decided by a coin flip in all but
# name. Recorded as confidence rather than as an abstention: the level is still the best reading
# of the evidence, and a teacher deciding how hard to look is exactly who the field is for.
_CLEAR_MARGIN = 0.25
_SOME_MARGIN = 0.10


def build_band_prompt(criterion: Criterion, kept: list[dict], band) -> str:
    """One band's question. The descriptor for THIS band only — the others are not shown.

    Showing the whole scale is what makes the category form a gestalt judgment. A model that can
    see band 6 while judging band 3 is comparing, and comparison is where the middle comes from.
    """
    return BAND_PROMPT.format(
        name=criterion.criterion_label,
        band=band,
        descriptor=criterion.descriptors.get(str(band), f"(no descriptor for level {band})"),
        evidence="\n".join(f"- {k['span']}" for k in kept))


def level_from(probabilities: dict, categories: list, threshold: float) -> dict:
    """The band, from the probabilities. Pure, so the decision can be argued with directly.

    ## The rule: the highest band whose whole ladder was climbed

    A paper is at band k if it cleared band 2, and band 3, ... and band k. NOT simply the highest
    band that happened to clear the threshold: a stray confident answer at band 6 under a failing
    band 4 does not promote anything, because "meets or exceeds 6" cannot be true while "meets or
    exceeds 4" is false. The ladder rule is what makes an incoherent answer harmless instead of
    a promotion.

    The bottom band needs no question. P(meets or exceeds the lowest band) is 1 by construction —
    everything meets the floor — so asking would spend a call on a known answer.

    ## Monotonicity is a free diagnostic

    Cumulative probabilities must be non-increasing as the bands rise. Violations are counted and
    reported rather than smoothed away: they say the descriptors are being read inconsistently,
    which is a fact about the rubric and the rater, and no single-category answer can produce it.
    """
    cats = sorted(float(c) for c in categories)
    probs = {float(k): float(v) for k, v in probabilities.items()}

    level, decided_at, decided_p = cats[0], None, None
    for c in cats[1:]:
        p_c = probs.get(c)
        if p_c is None or p_c < threshold:
            decided_at, decided_p = c, p_c
            break
        level = c
    else:
        # Every band cleared. The margin that matters is the top one's.
        decided_at, decided_p = cats[-1], probs.get(cats[-1])

    ordered = [probs[c] for c in cats[1:] if c in probs]
    violations = sum(1 for a, b in zip(ordered, ordered[1:]) if b > a + 1e-9)

    margin = None if decided_p is None else abs(decided_p - threshold)
    confidence = ("low" if margin is None or margin < _SOME_MARGIN
                  else "high" if margin >= _CLEAR_MARGIN else "medium")

    return {"level": level, "confidence": confidence,
            "decided_at": decided_at, "decided_p": decided_p,
            "monotonicity_violations": violations,
            "probabilities": {str(_fmt(c)): probs[c] for c in cats if c in probs}}


def score_criterion_cumulative(text: str, criterion: Criterion, rater: Rater, *,
                               threshold: float = DEFAULT_THRESHOLD,
                               concurrency: int = 8) -> tuple[Outcome, Usage]:
    """Stage C, then one call per band above the floor, then arithmetic.

    The model never chooses a level here. It answers a yes/no question with a probability, once
    per band, and the level is computed — so the step where a category was being hedged toward the
    middle no longer exists.
    """
    proposed, usage = rater.propose_spans(build_evidence_prompt(criterion, text))
    kept, dropped = verify_all(proposed, text)
    evidence = {"proposed": len(proposed), "kept": kept, "dropped": dropped,
                "norm_version": NORM_VERSION}

    if not kept:
        return (Outcome(
            node_id=criterion.node_id, node_version_id=criterion.node_version_id,
            status="no_verified_evidence", level=None,
            reason=("No proposed span survived verification. This is not a low score — the "
                    "criterion routes to a human."),
            reason_code=NO_SPANS_PROPOSED if not proposed else NO_VERIFIED_EVIDENCE,
            evidence=evidence), usage)

    bands = sorted(float(c) for c in criterion.categories)[1:]
    jobs = [(lambda b=b: _one_band(rater, criterion, kept, b)) for b in bands]
    answers, band_usage = _gather_bands(jobs, concurrency)
    usage = usage + band_usage

    probs = {b: a["probability"] for b, a in zip(bands, answers)}
    decided = level_from(probs, criterion.categories, threshold)

    evidence |= {"bands": decided["probabilities"], "threshold": threshold,
                 "decided_at": decided["decided_at"], "decided_p": decided["decided_p"],
                 "monotonicity_violations": decided["monotonicity_violations"],
                 "band_reasons": {str(b): a.get("reason") for b, a in zip(bands, answers)}}

    at, p_at = decided["decided_at"], decided["decided_p"]
    reason = (f"Cleared every band up to {decided['level']:g}. "
              + (f"Band {at:g} came back at p={p_at:.2f} against a threshold of {threshold:g}."
                 if p_at is not None else f"Band {at:g} was not answered."))
    if decided["monotonicity_violations"]:
        # Named in the reason, not just the evidence blob. A rater whose bands contradict each
        # other produced this level, and whoever reads it should know that before trusting it.
        reason += (f" {decided['monotonicity_violations']} band(s) contradicted a lower band, "
                   f"which should be impossible for a cumulative judgment.")

    return (Outcome(node_id=criterion.node_id, node_version_id=criterion.node_version_id,
                    status="scored", level=decided["level"],
                    confidence=decided["confidence"], reason=reason, evidence=evidence),
            usage)


def _one_band(rater: Rater, criterion: Criterion, kept: list[dict], band: float) -> dict:
    raw, usage = rater.judge_band(build_band_prompt(criterion, kept, _fmt(band)))
    return {"probability": float(raw.get("probability", 0.0)),
            "reason": raw.get("reason"), "_usage": usage}


def _fmt(band: float):
    """Descriptors are keyed by the category as written — "3", not "3.0"."""
    return int(band) if float(band).is_integer() else band


def _gather_bands(jobs: list, concurrency: int) -> tuple[list[dict], Usage]:
    """Same shape as `gather_criteria`, and separate because the payloads differ.

    The bands of ONE criterion go out together. They are independent questions about the same
    evidence — nothing in band 4's answer belongs in band 5's context, and running them
    concurrently makes that structural rather than merely true.
    """
    if concurrency <= 1 or len(jobs) <= 1:
        answers = [j() for j in jobs]
    else:
        with ThreadPoolExecutor(max_workers=min(concurrency, len(jobs))) as pool:
            answers = list(pool.map(lambda j: j(), jobs))
    total = Usage()
    for a in answers:
        total = total + a.pop("_usage")
    return answers, total


def score_criterion(text: str, criterion: Criterion, rater: Rater) -> tuple[Outcome, Usage]:
    """One criterion, by whichever stage-D form this rater is.

    The method comes off the rater's own identity rather than being passed down. A rater IS its
    method — two configurations differing only in it produce different bodies of scores, so they
    hash differently and MFRM holds them apart — and threading it through every caller would let
    the two disagree.
    """
    identity = getattr(rater, "identity", None)
    if identity is not None and getattr(identity, "level_method", "category") == "cumulative":
        return score_criterion_cumulative(
            text, criterion, rater, threshold=identity.level_threshold)
    return _score_criterion_category(text, criterion, rater)


def _score_criterion_category(text: str, criterion: Criterion,
                              rater: Rater) -> tuple[Outcome, Usage]:
    """The original form: one call that names a band. The second is not made when the first yields nothing
    verifiable — there is no point paying a model to judge an empty evidence list, and a model
    handed one will produce a level anyway."""
    proposed, usage = rater.propose_spans(build_evidence_prompt(criterion, text))
    kept, dropped = verify_all(proposed, text)
    evidence = {"proposed": len(proposed), "kept": kept, "dropped": dropped,
                "norm_version": NORM_VERSION}

    if not kept:
        return (Outcome(
            node_id=criterion.node_id, node_version_id=criterion.node_version_id,
            status="no_verified_evidence", level=None,
            reason=("No proposed span survived verification. This is not a low score — the "
                    "criterion routes to a human."),
            reason_code=NO_SPANS_PROPOSED if not proposed else NO_VERIFIED_EVIDENCE,
            evidence=evidence), usage)

    raw, u2 = rater.assign_level(build_score_prompt(criterion, kept))
    usage = usage + u2
    return _interpret(raw, criterion, evidence), usage


def _interpret(raw: dict, criterion: Criterion, evidence: dict) -> Outcome:
    """Turn what the model returned into an outcome the record can hold.

    Three ways a level fails to be a level, all of which route to a human rather than to a number:
    the model abstained; it returned no level while claiming not to have abstained; it returned a
    level that is not on this node's scale. The last is the one worth naming — a 3.5 on a
    four-point scale is not a near miss to round, it is a rater that was not scoring this node,
    and rounding it would put a number nobody assigned into a growth claim.
    """
    def out(status, **kw):
        return Outcome(node_id=criterion.node_id, node_version_id=criterion.node_version_id,
                       status=status, confidence=raw.get("confidence"),
                       reason=raw.get("reason"), evidence=evidence, **kw)

    if raw.get("abstain"):
        return out("abstained", level=None, reason_code=MODEL_ABSTAINED)
    level = raw.get("level")
    if level is None:
        return out("abstained", level=None, reason_code=NO_LEVEL_RETURNED)
    if not any(float(c) == float(level) for c in criterion.categories):
        return out("abstained", level=None, reason_code=OFF_SCALE)
    return out("scored", level=float(level))


# How many criteria of one artifact are in flight at once. Eight is the PERSUADE trait count, so
# a paper's whole trait set goes out together and the paper costs about as long as its slowest
# criterion instead of the sum of all of them.
#
# Measured on the first corpus wave: sixteen sequential calls took 72 seconds a paper, which is
# ~4.5s of waiting per call and no CPU to speak of. Six hours for a 331-paper wave, all of it
# spent idle. The calls do not become cheaper by overlapping — the token bill is identical — they
# only stop being consecutive.
#
# NOT parallel across artifacts. One artifact is one transaction and one `bound -> scored`
# transition, and the guard that refuses to write a second rater's scores into a half-scored
# artifact is worth more than another multiple of speed.
DEFAULT_CONCURRENCY = 8


def score_artifact(text: str, criteria: list[Criterion], rater: Rater, *,
                   concurrency: int = DEFAULT_CONCURRENCY) -> tuple[list[Outcome], Usage]:
    """Every criterion of one artifact, independently.

    Independently is the load-bearing word: no criterion's result is passed into the next call,
    and nothing accumulates between them but the token count. Halo is not something a model is
    asked to avoid — it is something the assembly makes unavailable.

    Running them concurrently is that claim made structural rather than merely true. A sequential
    loop leaves an ordering for a later edit to start depending on; threads leave none, and the
    only thing joined at the end is a token count, which is a sum and does not care.

    `concurrency=1` is the old sequential path exactly, kept as an argument rather than deleted
    because it is what a rate limit gets dialled down to, and what a confusing result gets
    reproduced under.
    """
    if is_non_attempt(text):
        return ([Outcome(node_id=c.node_id, node_version_id=c.node_version_id,
                         status="not_scorable", reason_code=EMPTY_DOCUMENT,
                         reason="The document is empty. No attempt was made against this task.",
                         evidence={"proposed": 0, "kept": [], "dropped": [],
                                   "norm_version": NORM_VERSION})
                 for c in criteria], Usage())

    return gather_criteria(
        [(lambda c=c: score_criterion(text, c, rater)) for c in criteria], concurrency)


def gather_criteria(jobs: list, concurrency: int) -> tuple[list[Outcome], Usage]:
    """Run the calls, in order out whatever the order back.

    `map` preserves input order, so an outcome list is positionally the criteria list no matter
    which criterion the model answered first. That matters beyond tidiness: `event_rows` pairs
    outcomes with criteria, and a scrambled list would attach every score to the wrong trait —
    silently, and in a way that reads as a terrible rater rather than as a bug.

    An exception propagates, and it propagates from the first job in ORDER rather than the first
    to fail — which is what the sequential version did too. The difference is that its siblings
    may already have been paid for by then. One artifact's worth of calls is the cost of a
    failure, the batch loop above catches it, and that was already true.
    """
    if concurrency <= 1 or len(jobs) <= 1:
        results = [j() for j in jobs]
    else:
        with ThreadPoolExecutor(max_workers=min(concurrency, len(jobs))) as pool:
            results = list(pool.map(lambda j: j(), jobs))

    total = Usage()
    for _, usage in results:
        total = total + usage
    return [outcome for outcome, _ in results], total
