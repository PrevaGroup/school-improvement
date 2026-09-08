"""The prompt text, versioned and fingerprinted — half of what identifies the rater.

A scoring configuration is a rater: model id + prompt versions + effort + the span verifier's
normalization rules, as one identity. Three of those four are values somebody types into a
configuration row and cannot get wrong by accident. The fourth is this file, and editing a string
here changes the rater without changing anything anybody would notice.

So the version is not the only thing recorded. `fingerprint()` hashes the actual text, the driver
refuses to run when a configuration's stamp disagrees with it, and `tests/test_prompts.py` pins
the current hashes. Editing a prompt therefore fails the test until the version is bumped in the
same commit — and a configuration promoted against the old version then refuses to run rather than
scoring papers with a rater nobody promoted.

That is the freeze made mechanical. "The scoring model is frozen for the POC" is otherwise a
sentence in a design document, and design documents do not stop a one-word edit.

WHAT THE PROMPTS ENCODE, and why it is here rather than in an instruction to the model:

  * one criterion per call      — a call emitting every row at once bakes in halo
  * one student per call        — a call holding the cohort makes the scale norm-referenced
  * no prior scores in stage D  — separate calls, separate assembly, no shared state
  * evidence before score       — stage D sees only spans that survived verification
  * no text features            — conventions is not in the trait set, and an error count puts it
                                  back in through the side door

Only the last is an instruction. The rest are properties of what goes into the context, which is
why `tests/test_score.py` asserts them against the assembled prompt rather than trusting the
wording.
"""
from __future__ import annotations

import hashlib

# Bump the version when the text changes. The test below will tell you if you forgot; the driver
# will refuse to run if a configuration still stamps the old one.
FIT_VERSION = "fit.1"
EVIDENCE_VERSION = "ev.1"
SCORE_VERSION = "sc.1"

# Stage B. The cheapest call on the path and the one with the worst failure mode, so almost all
# of this prompt is spent narrowing what "no" is allowed to mean.
#
# The gate exists to stop spend on work that is not a response to the task — a blank template, the
# assignment sheet, last week's essay dropped in the same folder. It does NOT exist to filter out
# weak writing, and a gate that drifts that way removes exactly the students the subsystem is most
# careful about, silently, before any criterion is ever scored. `not_scorable` means a defined
# non-attempt against the bound task. It never means bad.
FIT_PROMPT = """You are deciding ONE thing about a document: is it an attempt at the assigned task?

TASK: {task}

DOCUMENT:
<text>
{text}
</text>

Answer `attempt` unless the document is clearly not a response to this task at all. Examples of
what is NOT an attempt: the assignment sheet or rubric itself, a blank or unfilled template, a
response to a visibly different assignment, or a file containing only a name and a heading.

`attempt` is the answer for all of the following, and this list is the point of this prompt:

- Writing that is short, unfinished, or stops mid-sentence.
- Writing that misunderstands the task, or argues the opposite of what was asked.
- Writing with heavy spelling, grammar or punctuation errors, or written in a mix of languages.
- Writing that is off-topic in substance but is plainly this student's attempt at this assignment.
- Anything you are unsure about.

A weak, confused or barely-started response IS an attempt. Judging its quality is a separate step
that happens later against a rubric, and answering `not_an_attempt` here removes the student from
that step entirely — so the only papers that belong on that side are the ones where there is
nothing to score, not the ones where there is little.

Give a one-sentence reason a teacher could check against the document."""

EVIDENCE_PROMPT = """You are extracting evidence for ONE criterion from ONE piece of student writing.

CRITERION: {name}
{levels}

STUDENT TEXT:
<text>
{text}
</text>

Identify the spans of the student's own writing that bear on this criterion — the passages a reader
would point at to justify any level on this scale, whether they support a high one or a low one.

- Every span must be copied EXACTLY from the text above, character for character. A paraphrased or
  reconstructed span will be dropped by a verifier, and the criterion may become unscorable.
- Prefer whole clauses or sentences over fragments.
- Return 0 to 5 spans. Zero is correct when the writing genuinely offers nothing on this criterion;
  do not manufacture evidence to fill the list.
- Do not assign a level and do not evaluate quality. That is a separate step."""

SCORE_PROMPT = """You are scoring ONE criterion of ONE piece of student writing against a rubric.

CRITERION: {name}
{levels}

VERIFIED EVIDENCE — confirmed to appear verbatim in the student's writing:
{evidence}

Assign the level whose descriptor this evidence meets. The scale is criterion-referenced: a level
means the writing meets that descriptor, not that it ranks anywhere against other students.

Set abstain to true instead of a level when the evidence genuinely does not let you place the
writing on this scale. Abstaining routes the criterion to a human scorer — a legitimate outcome,
and better than a guess.

Judge only this criterion. Say nothing about spelling, grammar or punctuation: they are not on this
scale, and the paper must not move up or down for them. The reason should be one or two sentences a
teacher could check against the evidence above."""

BAND_VERSION = "bd.1"

# Stage D, the cumulative form. ONE band, ONE question, one call.
#
# The category form asks "which of these six bands is this?" and the answer clusters in the
# middle: measured on the first anchor wave, humans used a range of 5 points and we used 0.87 —
# 17% of their scale — with zero 6s awarded across 334 papers. The span diagnostic then showed the
# evidence was not the problem: verified characters rise monotonically with the human score, and
# in 9 of 10 traits that evidence predicts the HUMAN score better than our own score does. The
# signal arrives and is discarded at the moment it becomes a category.
#
# So the model is never asked to pick a band. It is asked, separately per band, whether the
# writing clears it — and the band is computed from the answers. There is no middle to retreat to
# in a question that has no middle.
#
# MEETS OR EXCEEDS, not "is exactly this band". That is what makes the answers cumulative and
# therefore checkable: they must be non-increasing as the bands rise, and a set that is not is
# incoherent in a way a single category answer can never be.
BAND_PROMPT = """You are judging ONE band of ONE criterion for ONE piece of student writing.

CRITERION: {name}

THE BAND — level {band}:
{descriptor}

VERIFIED EVIDENCE — confirmed to appear verbatim in the student's writing:
{evidence}

Answer one question: what is the probability that this writing MEETS OR EXCEEDS this band?

Meets or exceeds, not "is exactly this band". Writing that clearly surpasses this descriptor still
meets it, so strong writing should score high on every band below its own.

Give a probability between 0 and 1, and use the whole range. 0.95 when the evidence plainly
satisfies the descriptor; 0.05 when it plainly does not. Answers clustered near 0.5 are not
caution — they are a refusal to judge, and they give every piece of writing the same score.

Judge only this band of this criterion, on this evidence. Say nothing about spelling, grammar or
punctuation: they are not on this scale. The reason should be one sentence a teacher could check
against the evidence above."""

FEEDBACK_VERSION = "fb.2"

# Versioned SEPARATELY from the scoring prompts, and stamped on the composition rather than on
# score_event. A configuration is the RATER: what produced a level. Feedback wording does not
# produce a level, and folding it into the rater identity would mean every improvement to a
# sentence invalidated a term of scores and forced a re-promotion — which would make better
# feedback expensive, and the freeze is not there to do that.
FEEDBACK_PROMPT = """You are drafting formative feedback for ONE student on ONE piece of their writing.
A teacher will read it, edit it if they choose, and decide whether it goes out. Write for the
student, not for the teacher.

STUDENT'S FIRST NAME: {first_name}

THEIR WRITING:
<text>
{text}
</text>

WHAT THE SCORING FOUND, criterion by criterion:
{findings}

Write three short parts.

1. One or two sentences naming the strongest thing in this piece, specifically. Point at something
   they actually did — a move, a sentence, a choice — not a quality they possess.

2. ONE revision move, beginning "One revision move." Name the passage, say what it currently does,
   and say what doing more would get them. One. A list of five is a list nobody acts on.

3. OPTIONAL, and only if there is something worth saying: one observation outside the rubric,
   beginning "One thing outside the rubric, so it does not change your score:". Leave it out
   entirely if you would be manufacturing something to fill it.

RULES, all of them firm:

- Double quotation marks are reserved for the student's OWN words, copied exactly, and every one
  you use must also appear in the `quotations` field character for character. Anything in double
  quotes is checked against their writing and will hold this message back if it is not there.
- To suggest wording of your own, write it WITHOUT quotation marks. Say: two sentences on what
  Breyer actually required. Not: two sentences on "what Breyer actually required". The marks are
  how a reader tells their sentence from yours, and borrowing them for a suggestion takes that
  distinction away.
- Keep the whole message under 250 words. Three short parts, not an essay — a student who stops
  reading halfway has received nothing.
- Do NOT state a level, a score, a grade, or a number of any kind about their performance.
- Say NOTHING about spelling, grammar, punctuation or formatting. They are not on this scale and
  the piece is not being judged on them.
- Say nothing about any criterion the scoring could not reach. Those go to the teacher, not to the
  student.
- Do not compare this student to anyone else, and do not refer to a class.
- Address them by first name once, at the start. No sign-off."""

# --------------------------------------------------------------------------- #
# Structured output schemas.
#
# No `maxItems`: the API rejects it in a json_schema output format. The "0 to 5 spans" bound is
# therefore instruction rather than constraint, and nothing downstream depends on it holding —
# verification is what actually bounds what reaches stage D.
# --------------------------------------------------------------------------- #
FIT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["attempt", "not_an_attempt"]},
        # Asked for separately so the gate cannot be confidently wrong cheaply: a model that has
        # to name what it thinks the document IS will not call a short essay a rubric.
        "document_is": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "document_is", "reason"],
    "additionalProperties": False,
}

EVIDENCE_SCHEMA: dict = {
    "type": "object",
    "properties": {"spans": {"type": "array", "items": {"type": "string"}}},
    "required": ["spans"],
    "additionalProperties": False,
}

BAND_SCHEMA: dict = {
    "type": "object",
    "properties": {
        # A number, not a category. The whole point is to defer the category decision to code
        # that cannot hedge.
        #
        # NO `minimum`/`maximum`. The API refuses them on a number:
        #   output_config.format.schema: For 'number' type, properties maximum, minimum are not
        #   supported
        # The range is enforced in `scoring.score._one_band` instead, which is the better place
        # regardless — a schema keyword the server accepts still would not tell us WHICH band came
        # back out of range, and an out-of-range probability is a rater malfunction worth naming
        # rather than a request to reject.
        "probability": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["probability", "reason"],
    "additionalProperties": False,
}

SCORE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "level": {"type": ["number", "null"]},
        "abstain": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reason": {"type": "string"},
    },
    "required": ["level", "abstain", "confidence", "reason"],
    "additionalProperties": False,
}


FEEDBACK_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        # Declared separately so verification is exact rather than a guess at where a quotation
        # started. Same trick as stage C: make the model name what it claims, then check it.
        "quotations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["message", "quotations"],
    "additionalProperties": False,
}


def render_scale(criterion_label: str, descriptors: dict, categories: list) -> str:
    """Render one node's scale for the prompt.

    A descriptor that is a LIST is rendered as the clauses it contains, not joined into prose. The
    C3 row of the observed rubric stacks three conditional judgments in one cell; flattening that
    hides exactly the thing two raters would score differently, and the registry linter flags it
    for the same reason. Rendering it faithfully is not an endorsement — it is refusing to launder
    the problem on the way into the context.

    Categories drive the order, not the descriptor dict's key order: the scale is the node's
    identity and a dict is not ordered by anything meaningful.
    """
    lines = []
    for cat in categories:
        d = descriptors.get(str(cat), descriptors.get(cat))
        if d is None:
            raise ValueError(
                f"{criterion_label}: no descriptor for category {cat!r}. The scale is the node's "
                f"identity, so a missing level is a broken node, not a gap to render around.")
        if isinstance(d, list):
            lines.append(f"Level {cat}:\n" + "\n".join(f"  - {c}" for c in d))
        else:
            lines.append(f"Level {cat}: {d}")
    return "\n".join(lines)


def feedback_fingerprint() -> dict:
    """The feedback composer's identity, stamped on the composition.

    Deliberately not part of `fingerprint()`. That one identifies the RATER, and a score's meaning
    does not change because a sentence in a feedback prompt was improved.
    """
    return {"feedback": {"version": FEEDBACK_VERSION, "sha256": _sha(FEEDBACK_PROMPT)}}


def fingerprint(level_method: str = "category") -> dict:
    """Version AND hash of each prompt, as the scoring configuration stamps it.

    The hash is what makes the version honest. A configuration carrying a version whose text has
    since moved is a rater that no longer matches its own description, and the driver treats that
    as a stop rather than a warning.
    """
    out = {
        "fit": {"version": FIT_VERSION, "sha256": _sha(FIT_PROMPT)},
        "evidence": {"version": EVIDENCE_VERSION, "sha256": _sha(EVIDENCE_PROMPT)},
    }
    # ONLY the stage-D prompt this rater actually uses. A cumulative rater never sends
    # SCORE_PROMPT and a category rater never sends BAND_PROMPT, so listing both would make every
    # existing configuration stop matching its own fingerprint the moment the other prompt was
    # added — and would claim a rater was promoted against text it never saw.
    out |= ({"band": {"version": BAND_VERSION, "sha256": _sha(BAND_PROMPT)}}
            if level_method == "cumulative"
            else {"score": {"version": SCORE_VERSION, "sha256": _sha(SCORE_PROMPT)}})
    return out


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf8")).hexdigest()[:16]


if __name__ == "__main__":     # prints what a configuration stamps, for the promotion CLI
    import argparse
    import json

    # The METHOD matters: a cumulative rater fingerprints the band prompt and a category rater
    # fingerprints the score prompt. Stamping the wrong one produces a configuration that refuses
    # to load at the first paper.
    _ap = argparse.ArgumentParser(description="the prompt fingerprint a configuration stamps")
    _ap.add_argument("--method", default="category", choices=("category", "cumulative"))
    print(json.dumps(fingerprint(_ap.parse_args().method)))
