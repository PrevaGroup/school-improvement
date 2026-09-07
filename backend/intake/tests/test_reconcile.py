"""Roster reconciliation — including the cases that motivate doing it as one assignment.

The two tests that matter most are `test_assignment_beats_independent_lookups` and
`test_a_duplicate_cannot_happen`: they are the reason this is a solver rather than a loop, and if
either stops passing the design argument has been lost even though everything still "works".
"""
from __future__ import annotations

import pytest

from intake.reconcile import (INFERRED, LOOKED_UP, NAME_FLOOR, Manifest, name_similarity,
                              reconcile)

ROSTER = [
    {"student_id": "s-maya", "display_name": "Maya Okonkwo", "email": "maya.o@school.edu"},
    {"student_id": "s-devon", "display_name": "Devon Ruiz", "email": "devon.r@school.edu"},
    {"student_id": "s-jiwoo", "display_name": "Ji-woo Han", "email": "jiwoo.h@school.edu"},
    {"student_id": "s-jordan", "display_name": "Jordan Pike", "email": "jordan.p@school.edu"},
]


def f(fid, **kw):
    return {"file_id": fid, **kw}


# --------------------------------------------------------------------------- #
# Deterministic before probabilistic
# --------------------------------------------------------------------------- #
def test_account_match_is_a_lookup():
    m = reconcile([f("d1", owner_email="maya.o@school.edu")], ROSTER)
    assert len(m.matched) == 1
    assert m.matched[0].student_id == "s-maya"
    assert m.matched[0].resolution_path == LOOKED_UP
    assert m.matched[0].basis == "owner_account"


def test_editor_fallback_when_the_teacher_owns_the_copy():
    """Where a teacher distributed copies from a template, ownership resolves to the teacher and
    editor history is the fallback — still a lookup, still stronger than reading a name."""
    m = reconcile([f("d1", owner_email="teacher@school.edu",
                     editor_emails=["teacher@school.edu", "devon.r@school.edu"])], ROSTER)
    assert m.matched[0].student_id == "s-devon"
    assert m.matched[0].resolution_path == LOOKED_UP
    assert m.matched[0].basis == "editor_account"


def test_name_match_is_recorded_as_an_inference():
    """A score whose binding was inferred has a different error profile from one looked up, and
    pooling them pools two populations."""
    m = reconcile([f("d1", name_signals=["Maya Okonkwo - final draft"])], ROSTER)
    assert m.matched[0].student_id == "s-maya"
    assert m.matched[0].resolution_path == INFERRED
    assert m.matched[0].basis == "name"


def test_an_account_always_outbids_a_name():
    """No amount of name agreement should outbid a verified account. The whole argument for the
    Docs-only constraint is that ownership resolves identity by lookup."""
    m = reconcile([f("d1", owner_email="devon.r@school.edu",
                     name_signals=["Maya Okonkwo"])], ROSTER)
    assert m.matched[0].student_id == "s-devon"


def test_inferred_rate_is_reported():
    """The earliest available signal that an integration has broken."""
    m = reconcile([f("d1", owner_email="maya.o@school.edu"),
                   f("d2", name_signals=["Devon Ruiz"])], ROSTER)
    assert m.inferred_rate == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Why it is one assignment
# --------------------------------------------------------------------------- #
def test_assignment_beats_independent_lookups():
    """The case that motivates the solver.

    Two files whose name signals both look most like 'Ji-woo Han'. Independent nearest-name lookups
    give both to her and leave Jordan Pike unexplained. The assignment cannot: taking the better
    pairing globally puts the weaker file where it actually belongs.
    """
    files = [f("d1", name_signals=["Ji-woo Han"]),
             f("d2", name_signals=["Ji woo Hann"])]
    best_for_both = max(ROSTER, key=lambda s: name_similarity("Ji-woo Han", s["display_name"]))
    assert best_for_both["student_id"] == "s-jiwoo", "both files do prefer the same student"

    m = reconcile(files, ROSTER)
    assigned = {x.file_id: x.student_id for x in m.matched}
    assert len(set(assigned.values())) == len(assigned), (
        "the solver assigned two files to one student — the constraint is not being enforced")


def test_a_duplicate_cannot_happen():
    """Independent lookups will happily assign two papers to one student. A solver cannot."""
    files = [f(f"d{i}", name_signals=["Maya Okonkwo"]) for i in range(3)]
    m = reconcile(files, ROSTER)
    ids = [x.student_id for x in m.matched]
    assert len(ids) == len(set(ids))


def test_no_evidence_is_not_a_match():
    """The solver has to pair something; that is not the same as having found something. A paper
    left unmatched is a teacher correcting one binding key — cheap. A paper matched to the wrong
    student attaches a score to the wrong trajectory."""
    m = reconcile([f("d1", name_signals=["completely unrelated words"])], ROSTER)
    assert m.matched == []
    assert m.unmatched_files == ["d1"]


def test_weak_similarity_is_below_the_floor():
    assert name_similarity("Maya Okonkwo", "Jordan Pike") < NAME_FLOOR


# --------------------------------------------------------------------------- #
# Absence is information
# --------------------------------------------------------------------------- #
def test_non_submitters_surface_as_a_fact_about_the_class():
    m = reconcile([f("d1", owner_email="maya.o@school.edu")], ROSTER)
    assert set(m.missing_students) == {"s-devon", "s-jiwoo", "s-jordan"}


def test_unreadable_is_not_the_same_as_missing():
    """A missing score and a file we lack permission to open mean different things to a teacher,
    and the manifest keeps them apart."""
    m = reconcile([f("d1", unreadable=True)], ROSTER)
    assert m.unreadable_files == ["d1"]
    assert m.unmatched_files == []
    assert len(m.missing_students) == 4


def test_the_prompt_is_classified_out_and_kept():
    """The assignment prompt or a blank template is routinely in these folders. It is not a
    submission — and it is worth keeping, because it is the task statement."""
    m = reconcile([f("handout", is_non_student=True),
                   f("d1", owner_email="maya.o@school.edu")], ROSTER)
    assert m.non_student_files == ["handout"]
    assert len(m.matched) == 1


def test_three_categories_stay_apart():
    m = reconcile([f("handout", is_non_student=True),
                   f("locked", unreadable=True),
                   f("mystery", name_signals=["???"]),
                   f("d1", owner_email="maya.o@school.edu")], ROSTER)
    s = m.summary()
    assert (s["non_student_files"], s["unreadable_files"], s["unmatched_files"]) == (1, 1, 1)
    assert s["matched"] == 1 and s["looked_up"] == 1


# --------------------------------------------------------------------------- #
# Name handling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("a,b", [
    ("Delgado, Sam", "Sam Delgado"),
    ("MAYA OKONKWO", "Maya Okonkwo"),
    ("Beltran, Amara", "Amara Beltrán"),
    ("ji-woo han final draft", "Ji-woo Han"),
])
def test_names_match_across_ordinary_variation(a, b):
    assert name_similarity(a, b) >= NAME_FLOOR, f"{a!r} vs {b!r}"


def test_empty_roster_or_folder_is_not_an_error():
    assert reconcile([], ROSTER).summary()["missing_students"] == 4
    assert reconcile([f("d1")], []).summary()["unmatched_files"] == 1
    assert isinstance(reconcile([], []), Manifest)
