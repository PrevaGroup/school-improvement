"""Stage B — the fit gate. Is this document an attempt at the bound task?

Design: the expansion plan §11 Phase 3 lists "fit gate" first on the scoring path, and §6 says
why it is there: "The fit gate at stage B prevents spend on inadmissible work." A folder of
twenty-eight papers against thirteen criteria is several hundred calls, and a blank template put
through all of them costs the same as an essay and produces thirteen abstentions.

## The failure mode this module is mostly about

A gate that is too eager does not save money, it removes students. `not_scorable` means a defined
non-attempt against the bound task — the structural-zero end of core's `value_status` vocabulary,
never weak performance — and a gate that drifted into judging quality would take exactly the
writers this subsystem exists to be careful about out of the record BEFORE any criterion was
scored, where nothing downstream could see it happen.

So three things hold it in place, and only the first is a prompt:

1. The prompt spends most of its length listing what still counts as an attempt: short, unfinished,
   misunderstood, error-ridden, off-topic, unsure. `is_non_attempt()` in `score.py` already refuses
   a word-count threshold for the same reason, in the same words.

2. `decide()` is asymmetric on purpose. A malformed answer, an unexpected verdict, an empty reason
   — anything other than a well-formed `not_an_attempt` — resolves to ADMIT. The expensive failure
   is scoring a rubric; the unrecoverable one is dropping a paper.

3. The verdict is recorded, not just acted on. A gated paper carries the model's own words for
   what it thought the document was, so a teacher looking at "we did not score this" can see the
   claim and disagree with it. A gate whose decisions are invisible is a gate nobody can audit.

## Why this is not `is_non_attempt`

`is_non_attempt` is deterministic and answers "is there anything on the page". This answers "is
what is on the page a response to THIS task", which needs the task statement and a judgment. They
are two gates and both stay: the cheap one first, and it costs nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from .prompts import FIT_PROMPT

# The reason code written to `artifact.state_reason_code` and to every criterion's event. Distinct
# from EMPTY_DOCUMENT so "there was nothing on the page" and "this was not this assignment" stay
# apart in the record — they call for different things from a teacher.
NOT_THIS_TASK = "not_an_attempt_at_task"

ADMIT = "attempt"
REFUSE = "not_an_attempt"


@dataclass(frozen=True)
class Verdict:
    """What the gate decided and why, in the model's own words."""
    admitted: bool
    document_is: str | None = None
    reason: str | None = None
    # False when the gate did not run at all — no task statement, or the configuration turned it
    # off. Distinct from admitted=True, because "we checked and it is fine" and "we did not check"
    # are different claims and the second must not be recorded as the first.
    checked: bool = True

    def as_evidence(self) -> dict:
        return {"gate": "fit", "admitted": self.admitted, "checked": self.checked,
                "document_is": self.document_is, "reason": self.reason}


def build_fit_prompt(task: str, text: str) -> str:
    return FIT_PROMPT.format(task=task, text=text)


def decide(raw: dict | None) -> Verdict:
    """Read the model's answer, resolving every ambiguity toward admitting the paper.

    The asymmetry is the design. A gate that admits a rubric wastes a few dollars and produces
    thirteen abstentions a teacher will dismiss in a second. A gate that refuses a real paper takes
    a student out of the record before anything is scored, and the only trace is a line saying
    their work was not an attempt. Those are not comparable errors, so they are not treated
    symmetrically.
    """
    if not isinstance(raw, dict):
        return Verdict(admitted=True, reason="the gate returned nothing readable")

    verdict = str(raw.get("verdict") or "").strip()
    if verdict != REFUSE:
        # Covers ADMIT and every malformed or unexpected value. A verdict this module does not
        # recognise is not a refusal; it is a gate that failed, and a failed gate admits.
        return Verdict(admitted=True, document_is=raw.get("document_is"),
                       reason=raw.get("reason"))

    reason = str(raw.get("reason") or "").strip()
    document_is = str(raw.get("document_is") or "").strip()
    if not reason or not document_is:
        # A refusal with nothing behind it is the one a teacher cannot argue with, because there is
        # nothing on screen to argue against.
        return Verdict(admitted=True, document_is=document_is or None,
                       reason="the gate refused the paper without saying what it was; admitted")

    return Verdict(admitted=False, document_is=document_is, reason=reason)


def check(task: str | None, text: str, rater) -> tuple[Verdict, object]:
    """Run the gate. Returns the verdict and the usage.

    No task statement means no gate. The question is "an attempt at WHAT", and without the task it
    collapses into "is this good writing" — which is the drift this module exists to prevent. A
    folder whose prompt file intake never found should cost more to score, not fewer students.
    """
    from .rater import Usage

    if not task or not task.strip():
        return Verdict(admitted=True, checked=False,
                       reason="no task statement was available, so fit was not assessed"), Usage()

    raw, usage = rater.judge_fit(build_fit_prompt(task.strip(), text))
    return decide(raw), usage
