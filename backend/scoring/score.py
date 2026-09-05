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

from dataclasses import dataclass, field

from .prompts import EVIDENCE_PROMPT, SCORE_PROMPT, render_scale
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


def score_criterion(text: str, criterion: Criterion, rater: Rater) -> tuple[Outcome, Usage]:
    """One criterion, two calls at most. The second is not made when the first yields nothing
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


def score_artifact(text: str, criteria: list[Criterion],
                   rater: Rater) -> tuple[list[Outcome], Usage]:
    """Every criterion of one artifact, independently.

    Independently is the load-bearing word: no criterion's result is passed into the next call,
    and nothing accumulates between them but the token count. Halo is not something a model is
    asked to avoid — it is something the assembly makes unavailable.
    """
    if is_non_attempt(text):
        return ([Outcome(node_id=c.node_id, node_version_id=c.node_version_id,
                         status="not_scorable", reason_code=EMPTY_DOCUMENT,
                         reason="The document is empty. No attempt was made against this task.",
                         evidence={"proposed": 0, "kept": [], "dropped": [],
                                   "norm_version": NORM_VERSION})
                 for c in criteria], Usage())

    outcomes, total = [], Usage()
    for c in criteria:
        outcome, usage = score_criterion(text, c, rater)
        outcomes.append(outcome)
        total = total + usage
    return outcomes, total
