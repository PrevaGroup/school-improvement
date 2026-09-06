"""What may reach a student, and what is held back.

Every check here fails toward holding. A held draft costs a teacher one click — `blocked` ->
`in_review` is a move a teacher may make. A draft that goes out having misquoted a student, or
having commented on spelling after a deliberate decision that spelling is not being judged, costs
something that cannot be clicked back.
"""
from __future__ import annotations

import pytest

from scoring.feedback import (EMPTY_DRAFT, MENTIONS_CONVENTIONS, OVERLONG_DRAFT, STATES_A_LEVEL,
                              UNDECLARED_QUOTATION, UNVERIFIED_QUOTATION, Draft, build_prompt,
                              check, draft, findings_for_prompt, first_name)
from scoring.prompts import feedback_fingerprint
from scoring.rater import RaterIdentity, Usage

PAPER = (
    "Tinker asked schools to prove something. The exceptions ask students to prove something "
    "instead. Bethel v. Fraser is where the drift starts, and the reasoning is about vulgarity "
    "while the effect is about power."
)

CRITERIA = [
    {"node_id": "n1", "criterion_label": "Controlling idea", "status": "scored", "level": 4.0,
     "scale_categories": [1, 2, 3, 4], "reason": "Holds a position throughout.",
     "evidence": ["Tinker asked schools to prove something."], "needs_human": False},
    {"node_id": "n2", "criterion_label": "Use of evidence", "status": "abstained", "level": None,
     "scale_categories": [1, 2, 3, 4], "reason": "Could not tell.", "evidence": [],
     "needs_human": True},
]
PACKET = {"student_id": "stu-1", "criteria": CRITERIA}


def make(message: str, quotations=None) -> Draft:
    return Draft(message=message, quotations=list(quotations or []),
                 composer_version="fb.1", fingerprint=feedback_fingerprint())


class FakeRater:
    def __init__(self, payload):
        self.identity = RaterIdentity("cfg-1", "claude-opus-5", "high", {}, "1")
        self.payload = payload
        self.prompts: list[str] = []

    def write_feedback(self, prompt):
        self.prompts.append(prompt)
        return dict(self.payload), Usage(1, 10, 5)


# ------------------------------------------------------------------ quotation integrity


def test_a_quotation_that_is_not_in_the_paper_holds_the_draft():
    """Misquoting a student back to themselves — putting words in their mouth and calling it their
    sentence — is the worst failure this surface has, and it is string matching."""
    d = make('Maya, your line "The Court abandoned Tinker entirely" does real work.',
             ["The Court abandoned Tinker entirely"])
    codes = [h.code for h in check(d, PAPER)]
    assert UNVERIFIED_QUOTATION in codes


def test_an_exact_quotation_passes():
    d = make('Maya, "Tinker asked schools to prove something." is the strongest line here.',
             ["Tinker asked schools to prove something."])
    assert check(d, PAPER) == []


def test_a_quotation_the_composer_did_not_declare_is_still_caught():
    """Without this, an invented sentence in quotation marks gets through by simply not being
    listed — which is the obvious way around a check on the declared list."""
    d = make('Maya, you wrote "the Court has abandoned all limits" and that overstates it.', [])
    codes = [h.code for h in check(d, PAPER)]
    assert UNDECLARED_QUOTATION in codes


def test_curly_quotes_are_caught_too():
    d = make("Maya, you wrote “the Court has abandoned all limits” here.", [])
    assert UNDECLARED_QUOTATION in [h.code for h in check(d, PAPER)]


def test_typographic_differences_do_not_hold_a_real_quotation():
    """The verifier folds typography and does not fold case. A composer emitting a curly
    apostrophe where the student typed a straight one is not misquoting them."""
    paper = "The Court's reasoning is about vulgarity."
    d = make("You wrote about the Court's reasoning.", ["The Court’s reasoning"])
    assert check(d, paper) == []


# ------------------------------------------------------------------ decided policy


@pytest.mark.parametrize("bad", [
    "Watch your spelling in the second paragraph.",
    "There are grammar problems throughout.",
    "Fix the punctuation around your quotations.",
    "A few typos to clean up.",
])
def test_a_conventions_comment_holds_the_draft(bad):
    """Conventions is not in the trait set. Raising it in the feedback channel puts it back
    through the side door, and the paper is not being judged on it."""
    assert MENTIONS_CONVENTIONS in [h.code for h in check(make(f"Maya, good work. {bad}"), PAPER)]


@pytest.mark.parametrize("bad", [
    "You earned a level 3 on this.",
    "Your score is strong.",
    "That puts you at 3 out of 4.",
    "You scored a 4 for the controlling idea.",
])
def test_stating_a_level_holds_the_draft(bad):
    """The number is the teacher's to hand back, not the message's to announce."""
    assert STATES_A_LEVEL in [h.code for h in check(make(f"Maya. {bad}"), PAPER)]


@pytest.mark.parametrize("fine", [
    "The Court said as much in 1969, and your paragraph on it lands.",
    "Tinker v. Des Moines is doing the work in your second paragraph.",
    "Two sentences on what Breyer required would help.",
])
def test_ordinary_numbers_and_case_names_do_not_hold_a_draft(fine):
    """A digit check would hold every paper about a court case. The pattern is narrow on purpose."""
    assert check(make(f"Maya, {fine}"), PAPER) == []


def test_an_empty_draft_is_held_and_nothing_else_is_reported():
    holds = check(make(""), PAPER)
    assert [h.code for h in holds] == [EMPTY_DRAFT]


def test_an_overlong_draft_is_held():
    assert OVERLONG_DRAFT in [h.code for h in check(make("Maya. " + "x" * 2100), PAPER)]


# ------------------------------------------------------------------ what the composer is shown


def test_a_criterion_that_needs_a_human_is_not_described_to_the_composer():
    """The scoring could not reach it, so there is nothing to tell a student — and a composer
    handed "we could not tell" will write around it rather than leave it alone."""
    out = findings_for_prompt(CRITERIA)
    assert "Controlling idea" in out
    assert "Use of evidence" not in out
    assert "Could not tell" not in out


def test_the_composer_sees_the_paper_because_the_scores_are_already_fixed():
    """Stage D is kept to verified spans because the text moves levels. Nothing here can move one:
    every level is written and score_event is append-only. What is left is the opposite risk —
    feedback that cannot refer to the paper is feedback nobody can act on."""
    prompt = build_prompt("Maya", PAPER, CRITERIA)
    assert PAPER[:50] in prompt
    assert "<text>" in prompt


def test_an_unresolved_student_gets_no_name_rather_than_a_database_key():
    assert first_name(None, "stu-1") == ""
    assert "stu-1" not in build_prompt(first_name(None, "stu-1"), PAPER, CRITERIA)


def test_a_first_name_is_taken_from_the_full_name():
    assert first_name("Maya Okonkwo", "stu-1") == "Maya"


def test_the_draft_carries_its_own_versioned_identity():
    """Stamped on the composition, not on score_event: a score's meaning does not change because a
    sentence in a feedback prompt was improved."""
    d, usage = draft(PAPER, PACKET, FakeRater(
        {"message": "Maya, the last line is the best thing here.", "quotations": []}), "Maya O")
    assert d.composer_version == "fb.1"
    assert d.fingerprint == feedback_fingerprint()
    assert usage.calls == 1
