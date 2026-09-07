"""Reading a folder: what each file turns out to be, and who it belongs to.

The classification is the easy half. The hard half is what a teacher is SHOWN when nothing
matched — three wrong names offered as candidates are worse than none, because a rushed teacher
accepts one and the paper is filed under a student who did not write it.
"""
from __future__ import annotations

import pytest

from intake.read_folder import (CANDIDATE_FLOOR, SourceFile, candidates_for, classify,
                                name_signals, rows_for)
from intake.reconcile import NAME_FLOOR

ROSTER = [{"student_id": f"stu-{i}", "display_name": n} for i, n in enumerate(
    ["Maya Okonkwo", "Devon Ruiz", "Ji-woo Han", "Amara Beltrán", "Sam Delgado", "Priya Raman"])]
NAMES = {s["student_id"]: s["display_name"] for s in ROSTER}

ESSAY = ("Tinker asked schools to prove something. The exceptions ask students to prove something "
         "instead, and the Court has never defended that reversal as a whole.")


def f(name, text=ESSAY, **kw):
    return SourceFile(source_ref=name, name=name, data=text.encode("utf8"), **kw)


# ------------------------------------------------------------------ what a filename offers


def test_the_whole_stem_and_its_parts_are_both_offered():
    """A submission is called "Maya Okonkwo - final draft.docx" far more often than anything tidy,
    and the whole stem is what matches when a student simply used their name."""
    out = name_signals("Maya Okonkwo - final draft.docx")
    assert "Maya Okonkwo" in out and "Maya Okonkwo - final draft" in out


def test_underscores_and_dashes_are_both_separators():
    assert "okonkwo" in name_signals("okonkwo_maya_oped.txt")
    assert "Maya Okonkwo" in name_signals("Maya Okonkwo—final.docx")


def test_the_extension_is_not_a_name_signal():
    assert not any(s.endswith(".docx") for s in name_signals("essay.docx"))


# ------------------------------------------------------------------ five outcomes


def test_a_real_paper_is_provisionally_resolved():
    assert classify(f("Maya Okonkwo - op-ed.txt"))[0] == "resolved"


def test_the_assignment_is_recognised_and_kept():
    """Worth keeping — it is the task statement — and not worth scoring, because scoring it
    produces a confident level for a paper nobody wrote."""
    status, body, reason = classify(f("Free Speech PROMPT.txt", "Write an op-ed of 600 words."))
    assert status == "not_student_work"
    assert reason == "looks_like_the_assignment"
    assert body, "the prompt's text is kept: it is the task statement"


def test_an_empty_document_is_empty_rather_than_unreadable():
    """Two different facts. A teacher chases a blank submission and an unreadable one differently."""
    assert classify(f("Devon Ruiz - op-ed.txt", "   \n\t "))[0] == "empty"


def test_a_format_we_cannot_open_is_unreadable_and_says_why():
    status, _, reason = classify(f("scan.pdf", "%PDF-1.7"))
    assert status == "unreadable"
    assert "pdf" in reason


def test_a_file_the_provider_could_not_hand_over_is_unreadable_whatever_its_name():
    """A permission error is an inventory discrepancy, not a student who did not write."""
    sf = f("Maya Okonkwo - op-ed.txt")
    sf.unreadable_reason = "the caller lacks permission to read this document"
    assert classify(sf) == ("unreadable", "", "source_unreadable")


def test_operating_system_clutter_is_not_a_submission():
    assert classify(f(".DS_Store", "\x00bink"))[0] == "not_student_work"


# ------------------------------------------------------------------ the stuck queue


def test_a_file_with_nothing_to_match_on_gets_no_candidates():
    """"Untitled document" shares letters with "Devon Ruiz" and that is a coincidence, not a lead.
    An empty candidate list is the honest answer to "nothing in this file says whose it is", and
    it is a DIFFERENT problem from "it might be one of these three"."""
    assert candidates_for(f("Untitled document.txt"), ROSTER, NAMES) == []


@pytest.mark.parametrize("noise", ["final draft v3.txt", "copy of essay.txt", "document.txt"])
def test_generic_filenames_produce_no_candidates(noise):
    assert candidates_for(f(noise), ROSTER, NAMES) == []


@pytest.mark.parametrize("near,expected", [
    ("Maya Okonkow essay.txt", "Maya Okonkwo"),      # transposed letters
    ("M Okonkwo - oped.txt", "Maya Okonkwo"),        # an initial
    ("Jiwoo Han final.txt", "Ji-woo Han"),           # the hyphen dropped
    ("Amara Beltran.txt", "Amara Beltrán"),          # the accent dropped
])
def test_a_genuine_near_miss_does_surface(near, expected):
    """The floor has to let a misspelling through or the stuck queue is useless — a teacher
    resolving by hand is exactly who needs the near-miss."""
    out = candidates_for(f(near), ROSTER, NAMES)
    assert out and out[0]["display_name"] == expected


def test_the_candidate_floor_sits_below_the_match_floor():
    """A candidate is by definition something that did NOT match. A floor at or above the match
    threshold would make the list permanently empty."""
    assert CANDIDATE_FLOOR < NAME_FLOOR


# ------------------------------------------------------------------ a whole folder


def test_a_folder_of_mixed_files_sorts_itself_out():
    files = [f("Maya Okonkwo - op-ed final.txt"),
             f("Devon Ruiz - op-ed final.txt"),
             f("Free Speech op-ed PROMPT.txt", "Write an op-ed of 600 words, due Friday."),
             f("Untitled document.txt")]
    rows, _ = rows_for(files, ROSTER, "manifest-1", "public")
    by_name = {r["name"]: r for r in rows}

    assert by_name["Maya Okonkwo - op-ed final.txt"]["resolved_student_id"] == "stu-0"
    assert by_name["Devon Ruiz - op-ed final.txt"]["resolved_student_id"] == "stu-1"
    assert by_name["Free Speech op-ed PROMPT.txt"]["status"] == "not_student_work"
    assert by_name["Untitled document.txt"]["status"] == "unresolved"


def test_a_file_nobody_matched_names_nobody():
    """The CHECK in 0021 refuses it, and so does this — a half-matched file quietly becoming
    somebody's paper is the failure both exist to prevent."""
    rows, _ = rows_for([f("Untitled document.txt")], ROSTER, "m-1", "public")
    assert rows[0]["resolved_student_id"] is None
    assert rows[0]["resolution_path"] is None


def test_every_file_in_the_folder_produces_a_row():
    """Twenty-seven files, twenty-four scores, nobody asking about the other three — that is the
    failure. Every file is accounted for, including the ones that are not submissions."""
    files = [f("a.pdf", "%PDF"), f(".DS_Store", "x"), f("Maya Okonkwo.txt"),
             f("blank.txt", "  ")]
    rows, _ = rows_for(files, ROSTER, "m-1", "public")
    assert len(rows) == 4
    assert {r["status"] for r in rows} == {"unreadable", "not_student_work", "resolved", "empty"}


def test_two_students_cannot_be_matched_to_one_paper():
    """The reconciliation is an assignment over the whole set, not a per-file best guess: a
    student can only have handed in one paper, and greedy matching lets a strong filename claim a
    student that a weaker-but-correct match then cannot have."""
    rows, _ = rows_for([f("Maya Okonkwo - draft.txt"), f("Maya Okonkwo - final.txt")],
                       ROSTER, "m-1", "public")
    matched = [r["resolved_student_id"] for r in rows if r["resolved_student_id"]]
    assert len(matched) == len(set(matched))
