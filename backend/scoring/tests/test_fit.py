"""The fit gate — and mostly, the ways a gate stops being a gate and starts being a filter.

"The fit gate at stage B prevents spend on inadmissible work." A folder of twenty-eight papers
against thirteen criteria is several hundred calls, and a blank template put through all of them
costs the same as an essay and produces thirteen abstentions.

The saving is not what this file is about. A gate that is too eager does not save money, it removes
students — `not_scorable` before any criterion is scored, where nothing downstream can see it
happen. So almost every test here is a case the gate must ADMIT, and the two errors are treated
asymmetrically on purpose: admitting a rubric wastes a few dollars, refusing a real paper takes a
child out of the record.
"""
from __future__ import annotations

from scoring.fit import ADMIT, NOT_THIS_TASK, REFUSE, Verdict, check, decide
from scoring.prompts import FIT_PROMPT, FIT_SCHEMA


def answer(verdict: str, document_is: str = "a student essay", reason: str = "it argues a claim"):
    return {"verdict": verdict, "document_is": document_is, "reason": reason}


class FakeRater:
    def __init__(self, raw):
        self.raw = raw
        self.prompts: list[str] = []

    def judge_fit(self, prompt):
        from scoring.rater import Usage
        self.prompts.append(prompt)
        return self.raw, Usage(calls=1)


# ------------------------------------------------------------------ what it refuses

def test_a_document_that_is_not_the_assignment_is_refused():
    v = decide(answer(REFUSE, "the assignment sheet", "it is the prompt, not a response"))
    assert not v.admitted and v.document_is == "the assignment sheet"


def test_a_refusal_carries_the_reason_a_teacher_will_read():
    """"We did not score this" with nothing behind it is a claim nobody can argue with. The
    record has to hold what the gate thought the document WAS, so a teacher can disagree."""
    v = decide(answer(REFUSE, "a blank template", "no writing has been added to the template"))
    assert v.reason and v.document_is
    assert v.as_evidence()["gate"] == "fit"


# ------------------------------------------------------------------ what it must admit

def test_an_admitted_paper_is_admitted():
    assert decide(answer(ADMIT)).admitted


def test_a_malformed_answer_admits():
    """A gate that failed is not a gate that refused. Every unreadable shape resolves the same
    way, because the alternative is a paper dropped by a parsing error."""
    for raw in (None, {}, [], "no", {"verdict": None}, {"verdict": "maybe"}, {"verdict": ""}):
        assert decide(raw).admitted, raw


def test_a_refusal_with_no_reason_admits():
    """The one refusal a teacher could not contest is the one with nothing on screen to contest.
    Rather than show it, the paper goes through."""
    assert decide(answer(REFUSE, "", "")).admitted
    assert decide({"verdict": REFUSE}).admitted
    assert decide(answer(REFUSE, "a rubric", "")).admitted
    assert decide(answer(REFUSE, "", "not a response")).admitted


def test_no_task_statement_means_no_gate_rather_than_a_guess():
    """The question is "an attempt at WHAT". Without the task it collapses into "is this good
    writing", which is the drift the gate exists to avoid. A folder whose prompt file intake never
    found should cost more to score, not fewer students."""
    r = FakeRater(answer(REFUSE, "junk", "junk"))
    for task in (None, "", "   "):
        v, usage = check(task, "Some student writing.", r)
        assert v.admitted and not v.checked
        assert usage.calls == 0, "the gate must not spend a call it cannot interpret"
    assert r.prompts == []


def test_not_checked_is_not_recorded_as_checked_and_fine():
    """Two different claims. "We looked and it is an attempt" and "we never looked" must not
    collapse into one flag, or the gate's coverage is unknowable afterwards."""
    skipped = Verdict(admitted=True, checked=False)
    looked = Verdict(admitted=True, checked=True)
    assert skipped.as_evidence()["checked"] is False
    assert looked.as_evidence()["checked"] is True


# ------------------------------------------------------------------ the prompt is the guard

def test_the_prompt_lists_what_still_counts_as_an_attempt():
    """Most of this prompt's length is spent narrowing what "no" may mean. These are the cases
    that would otherwise remove exactly the writers the subsystem is most careful about."""
    p = FIT_PROMPT.lower()
    for case in ("short", "unfinished", "misunderstands", "spelling", "off-topic", "unsure"):
        assert case in p, f"the prompt no longer protects {case!r} writing"


def test_the_prompt_says_a_weak_response_is_an_attempt():
    p = FIT_PROMPT.lower()
    assert "is an attempt" in p
    assert "quality" in p, "the prompt must say that judging quality happens elsewhere"


def test_the_prompt_says_what_refusing_costs():
    """A model told only what to look for will find it. This one is told what happens to a student
    when it answers no, which is the fact that should make it cautious."""
    assert "removes the student" in FIT_PROMPT


def test_the_gate_must_name_what_it_thinks_the_document_is():
    """Asked for separately so the gate cannot be confidently wrong cheaply. A model that has to
    name the document will not call a short essay a rubric."""
    assert "document_is" in FIT_SCHEMA["properties"]
    assert "document_is" in FIT_SCHEMA["required"]
    assert FIT_SCHEMA["properties"]["verdict"]["enum"] == [ADMIT, REFUSE]


# ------------------------------------------------------------------ the record

def test_a_gated_paper_says_it_was_the_wrong_task_not_that_it_was_empty():
    """`not_scorable` covers both, and they call for different things from a teacher: one is "you
    handed in nothing", the other is "you handed in the wrong thing". Collapsing them would make
    the more common and more fixable case invisible."""
    from scoring.score import EMPTY_DOCUMENT

    assert NOT_THIS_TASK != EMPTY_DOCUMENT
    assert "task" in NOT_THIS_TASK


def test_the_gate_runs_before_the_expensive_calls():
    """Its whole purpose. A gate that ran after scoring would be a label, not a saving."""
    import inspect

    from scoring import run_scoring

    src = inspect.getsource(run_scoring._score_one)
    assert src.index("fit.check") < src.index("score_artifact(")


def test_a_refused_paper_makes_no_scoring_calls():
    """The saving, asserted rather than assumed."""
    import inspect

    from scoring import run_scoring

    src = inspect.getsource(run_scoring._score_one)
    gate = src.index("if not verdict.admitted:")
    call = src.index("score_artifact(")
    assert gate < call, "scoring is not behind the gate"
    assert "else:" in src[gate:call], "the scoring call is not in the gate's else branch"


def test_the_fit_prompt_is_part_of_the_rater_identity():
    """Adding a stage changes what a score means, so a configuration promoted before the gate
    existed must refuse to run rather than quietly score with a rater nobody approved."""
    from scoring.prompts import fingerprint

    assert "fit" in fingerprint()
