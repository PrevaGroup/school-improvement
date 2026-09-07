"""Draft the message a student will read, and decide whether it may go in front of a teacher.

The teacher reviews the drafted feedback and the scores TOGETHER — a score approved without seeing
the message it produces is half a review. So the draft is built during composition, not after it,
and `composed -> in_review` is the machine saying the draft cleared its checks.

## Why stage E may see the paper when stage D may not

Stage D is kept to verified spans because an A/B probe showed that giving it the full text moved
scores — non-uniformly across traits, which is a change in what is being measured rather than a
refinement of it.

That argument does not transfer here, and it is worth being explicit about why rather than applying
the rule out of habit. Stage D's problem is that the text can move a level. By the time this runs,
every level is written and `score_event` is append-only, so nothing this stage sees can change one.
What is left is the opposite risk: feedback that cannot refer to the paper is feedback nobody can
act on. "Your Mahanoy paragraph says the Court moved back toward the student and then stops" is the
whole value, and it is unsayable from spans alone.

## The check that matters

Every quotation is verified against the student's own writing with the same deterministic verifier
stage C uses. Misquoting a student back to themselves — putting words in their mouth and calling it
their sentence — is the worst failure this surface has, and it is string matching.

The model must DECLARE its quotations, and the message is then scanned for quoted text that was not
declared, so nothing gets through by not being listed.

## Holding is cheap and sending is not

A held draft costs a teacher one click: `blocked -> in_review` is a move a teacher may make. A draft
that goes out with a conventions comment in it violates a decision that was made deliberately —
conventions is not in the trait set, and putting it back through the feedback channel is the side
door. So every check here fails toward holding, and the false-positive rate is a price worth paying
in that direction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .prompts import FEEDBACK_PROMPT, FEEDBACK_VERSION, feedback_fingerprint
from .rater import Rater, Usage
from .verify import verify, verify_all

# Hold codes. A code is what a queue can count; the message is for whoever opens it.
UNVERIFIED_QUOTATION = "unverified_quotation"
UNDECLARED_QUOTATION = "undeclared_quotation"
MENTIONS_CONVENTIONS = "mentions_conventions"
STATES_A_LEVEL = "states_a_level"
EMPTY_DRAFT = "empty_draft"
OVERLONG_DRAFT = "overlong_draft"

# A RUNAWAY GUARD, not a style rule. The first run held a 2042-character draft against a
# 2000-character cap, which is a 2% overshoot on a message nothing was wrong with — and the prompt
# had never told the composer a limit at all, so it was being held to a number it could not see.
#
# The checker's job is catching failure, not enforcing taste. Length is now the prompt's business
# (250 words, stated), and this is only here to stop something that has genuinely run away.
MAX_CHARS = 4000

# Conventions is not in the trait set. A feedback message that comments on it puts it back through
# the side door, and the paper is not being judged on it — so the message must not raise it either.
_CONVENTIONS = re.compile(
    r"\b(spelling|spelled|grammar|grammatical|punctuation|comma|commas|apostrophe|typo|typos|"
    r"capitalis?z?ation|misspell\w*|proofread\w*)\b", re.I)

# Narrow on purpose. "1969" and "Tinker v. Des Moines" are not scores; "a level 3" and "you scored"
# are. A digit check would hold every paper about a court case.
_STATES_LEVEL = re.compile(
    r"\b(level\s*\d|score[ds]?\s*(a|an)?\s*\d|\d\s*(out\s*of|/)\s*\d|"
    r"(your|a)\s+(score|grade|mark)\b|scored\s+(a|an)\b)", re.I)

# The one place the prompt REQUIRES the words "your score" — and the first real run held both
# papers because of it. The off-rubric note must open "so it does not change your score", which the
# pattern above matched. A checker that forbids what the prompt mandates blocks every draft that
# follows its instructions, and the two were written far enough apart that neither looked wrong on
# its own. `test_the_prompts_own_mandated_phrases_pass_every_check` now runs the instructions
# through the checks, so the next contradiction of this kind fails a test rather than a run.
_SANCTIONED = re.compile(r"so it does(?: not|n't) change your score", re.I)

# Quoted runs, straight or curly. Four characters minimum: shorter than that is punctuation noise
# rather than a claim about what the student wrote.
_QUOTED = re.compile(r'"([^"\n]{4,})"|“([^”\n]{4,})”')


@dataclass(frozen=True)
class Hold:
    code: str
    detail: str


@dataclass(frozen=True)
class Draft:
    message: str
    quotations: list[str]
    composer_version: str
    fingerprint: dict


def findings_for_prompt(criteria: list[dict]) -> str:
    """What the composer is told about the scoring.

    Criteria that need a human are omitted entirely. The scoring could not reach them, so there is
    nothing to tell a student about them, and a composer handed "we could not tell" will write
    around it rather than leave it alone.
    """
    lines = []
    for c in criteria:
        if c.get("needs_human") or c.get("status") != "scored":
            continue
        label = c.get("criterion_label") or c["node_id"]
        lines.append(f"- {label}: level {c['level']} of "
                     f"{max(c.get('scale_categories') or [c['level']])}. {c.get('reason') or ''}")
        for span in c.get("evidence") or []:
            lines.append(f'    evidence: "{span}"')
    return "\n".join(lines) if lines else "(nothing was scorable on this piece)"


def first_name(student_name: str | None, student_id: str) -> str:
    """Best available. A message that opens with an identifier is worse than one that opens with
    nothing, so an unresolved student gets no name rather than a database key."""
    if student_name and student_name.strip():
        return student_name.strip().split()[0]
    return ""


def build_prompt(name: str, text: str, criteria: list[dict]) -> str:
    return FEEDBACK_PROMPT.format(first_name=name or "(name unknown — do not address by name)",
                                  text=text, findings=findings_for_prompt(criteria))


def draft(text: str, packet: dict, rater: Rater, student_name: str | None = None
          ) -> tuple[Draft, Usage]:
    name = first_name(student_name, packet.get("student_id") or "")
    raw, usage = rater.write_feedback(build_prompt(name, text, packet["criteria"]))
    return Draft(message=(raw.get("message") or "").strip(),
                 quotations=list(raw.get("quotations") or []),
                 composer_version=FEEDBACK_VERSION,
                 fingerprint=feedback_fingerprint()), usage


def check(d: Draft, paper_text: str) -> list[Hold]:
    """Everything that would stop this message going in front of a teacher as ready."""
    holds: list[Hold] = []

    if not d.message:
        return [Hold(EMPTY_DRAFT, "the composer returned nothing")]
    if len(d.message) > MAX_CHARS:
        holds.append(Hold(OVERLONG_DRAFT,
                          f"{len(d.message)} characters; the cap is {MAX_CHARS}"))

    _, dropped = verify_all(d.quotations, paper_text)
    for miss in dropped:
        holds.append(Hold(UNVERIFIED_QUOTATION,
                          f"quoted as the student's words but not in their writing: "
                          f"{miss['span']!r}"))

    # Anything in quotation marks that was not declared. Without this, a composer could put an
    # invented sentence in quotes and simply not list it.
    for m in _QUOTED.finditer(d.message):
        quoted = m.group(1) or m.group(2)
        if not verify(quoted, paper_text)["ok"] and not any(
                quoted in q for q in d.quotations):
            holds.append(Hold(UNDECLARED_QUOTATION,
                              f"quoted in the message, not declared and not in the paper: "
                              f"{quoted!r}"))

    if m := _CONVENTIONS.search(d.message):
        holds.append(Hold(MENTIONS_CONVENTIONS,
                          f"raises conventions ({m.group(0)!r}), which is not in the trait set"))

    # The sanctioned clause is REMOVED before scanning rather than whitelisted afterwards: a draft
    # that says both "does not change your score" and "you scored a 4" must still be held.
    if m := _STATES_LEVEL.search(_SANCTIONED.sub(" ", d.message)):
        holds.append(Hold(STATES_A_LEVEL,
                          f"states a level or grade ({m.group(0)!r}); the number is the teacher's "
                          f"to hand back, not the message's to announce"))

    return holds
