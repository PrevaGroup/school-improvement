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
EVIDENCE_VERSION = "ev.1"
SCORE_VERSION = "sc.1"

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

FEEDBACK_VERSION = "fb.1"

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

- Quote the student's own words EXACTLY when you refer to their text, and list every quotation you
  used in the `quotations` field, character for character as it appears above. A quotation that
  does not appear in their writing will hold this message back from being sent.
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
EVIDENCE_SCHEMA: dict = {
    "type": "object",
    "properties": {"spans": {"type": "array", "items": {"type": "string"}}},
    "required": ["spans"],
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


def fingerprint() -> dict:
    """Version AND hash of each prompt, as the scoring configuration stamps it.

    The hash is what makes the version honest. A configuration carrying a version whose text has
    since moved is a rater that no longer matches its own description, and the driver treats that
    as a stop rather than a warning.
    """
    return {
        "evidence": {"version": EVIDENCE_VERSION, "sha256": _sha(EVIDENCE_PROMPT)},
        "score": {"version": SCORE_VERSION, "sha256": _sha(SCORE_PROMPT)},
    }


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf8")).hexdigest()[:16]


if __name__ == "__main__":     # `python -m scoring.prompts` prints what a configuration stamps
    import json

    print(json.dumps(fingerprint()))
