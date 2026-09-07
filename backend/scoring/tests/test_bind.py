"""What happens to a file the second time a teacher presses sync.

`decide` is four lines and carries the money: get it wrong in one direction and every sync
re-scores the class at the price of a class, get it wrong in the other and a student who rewrote
their paper keeps the score from the version they threw away.
"""
from __future__ import annotations

import pytest

from scoring.bind import BINDABLE, decide, initial_state, resolution_path


def intake_row(status="resolved", text_hash="hash-1", **kw):
    row = {"status": status, "text_hash": text_hash, "resolved_student_id": "stu-1",
           "resolution_path": "looked_up", "resolution_basis": "owner_account",
           "reason_code": None}
    row.update(kw)
    return row


def artifact(content_hash="hash-1", artifact_id="art-1", state="released"):
    return {"artifact_id": artifact_id, "content_hash": content_hash, "state": state}


# ------------------------------------------------------------------ the sync decision


def test_the_same_file_seen_again_is_skipped():
    """The common case every time a teacher presses sync. Treating it as new would re-score the
    whole class, and charge for it."""
    action, reason = decide(intake_row(), artifact())
    assert action == "skip"
    assert "unchanged" in reason


def test_a_changed_text_supersedes_rather_than_replacing():
    """A student who kept working handed in a different TEXT. The old artifact keeps its scores,
    its reviewer and its delivery record — that is what lets a growth claim over the pair be
    qualified honestly, instead of quietly overwritten."""
    action, reason = decide(intake_row(text_hash="hash-2"), artifact("hash-1"))
    assert action == "supersede"
    assert "art-1" in reason


def test_a_file_with_nothing_before_it_is_created():
    assert decide(intake_row(), None)[0] == "create"


def test_a_touched_but_unchanged_document_is_still_skipped():
    """Drive bumps `modified_at` when a student opens a document and changes nothing. Comparing
    times rather than text would re-score a class for having been looked at.

    Asserted behaviourally rather than by scanning the source — a source scan for "modified"
    matched this function's own docstring explaining why it does not use it, which is the second
    time today a prose-matching test has claimed something the code did not say.
    """
    touched = intake_row(modified_at="2026-09-06T23:59:00Z", size_bytes=99999)
    assert decide(touched, artifact("hash-1"))[0] == "skip"


def test_an_already_released_artifact_is_still_superseded_when_the_text_changes():
    """Released is terminal for THAT artifact, not for the binding key. A student who rewrites
    after feedback produces a new paper, and refusing it here would make the revision invisible."""
    assert decide(intake_row(text_hash="hash-2"), artifact("hash-1", state="released"))[0] \
        == "supersede"


# ------------------------------------------------------------------ where an artifact starts


def test_everything_starts_unbound_including_files_we_resolved():
    """`unbound -> bound` is a teacher's move and the trigger enforces it. Inserting straight into
    `bound` would bypass the state machine, which is exactly what an INSERT can do — the trigger
    is BEFORE UPDATE."""
    assert initial_state(intake_row())[0] == "unbound"
    assert initial_state(intake_row(status="unresolved", resolved_student_id=None))[0] == "unbound"


def test_an_unresolved_file_carries_why_it_could_not_be_bound():
    _, reason = initial_state(intake_row(status="unresolved", resolved_student_id=None))
    assert reason == "no_student_matched"


def test_a_resolved_file_carries_no_reason_code():
    """A reason on a state nothing went wrong in is noise that later reads as a problem."""
    assert initial_state(intake_row())[1] is None


# ------------------------------------------------------------------ what the binding records


def test_three_of_the_four_binding_elements_are_declared_not_inferred():
    """A teacher asserted what the folder is. Only the student is worked out from evidence, and
    keeping that distinction is what makes `resolution_path` mean anything."""
    p = resolution_path(intake_row())
    assert p["section"] == p["task"] == p["iteration"] == "declared"
    assert p["student"] == "looked_up"


def test_an_inferred_student_is_recorded_as_inferred():
    """A score whose student was inferred from a filename has a different error profile from one
    looked up from an account. Pooling them pools two populations."""
    p = resolution_path(intake_row(resolution_path="inferred", resolution_basis="name"))
    assert p["student"] == "inferred"
    assert p["basis"] == "name"


def test_an_unmatched_file_says_so_rather_than_claiming_a_path():
    p = resolution_path(intake_row(status="unresolved", resolution_path=None,
                                   resolution_basis=None))
    assert p["student"] == "unresolved"


# ------------------------------------------------------------------ what may become a paper


@pytest.mark.parametrize("status", ["resolved", "empty", "unresolved"])
def test_a_file_that_could_be_somebodys_writing_becomes_an_artifact(status):
    """`empty` included: a blank document from a named student is a non-attempt, which is a real
    outcome on that student's record rather than a file to drop. `unresolved` included: a paper
    that exists in a folder and nowhere in the system is the failure the statuses exist to
    prevent."""
    assert status in BINDABLE


@pytest.mark.parametrize("status", ["not_student_work", "unreadable"])
def test_the_assignment_and_the_unopenable_do_not_become_papers(status):
    """The first is the task statement; the second is an inventory discrepancy. Neither is
    anybody's writing, and scoring either produces a confident level for a paper nobody wrote."""
    assert status not in BINDABLE
