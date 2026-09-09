"""The class trait profile — what it says, and what it refuses to say.

`/review/home` records a deliberate restraint: "Still no aggregation over anyone's writing: every
number is a count of papers in a state. There is no class average here for the same reason there
is none in the queue."

This page crosses that line on purpose, and these tests are where the crossing is bounded. The
unit is the TRAIT, never the student: how did this class do on counterclaims against how they did
on evidence. Nothing here ranks a student, and nothing spans traits for one student — which is the
number that would turn a lesson-planning page into a leaderboard.
"""
from __future__ import annotations

from app.review_view import build_profile


def row(node="h", label="Overall quality", cats=(1, 2, 3, 4, 5, 6), status="scored",
        level=3, reason=None, n=1):
    return {"node_id": node, "criterion_label": label, "scale_categories": list(cats),
            "status": status, "level": level, "reason_code": reason, "n": n}


def test_each_trait_is_summarised_on_its_own_scale():
    """A mean of 2.4 sits near the bottom of a 1-6 scale and near the top of a 1-3 one. Comparing
    raw means across traits would make the elements look strong and the holistic weak by
    arithmetic rather than by anything a class did."""
    out = {t["label"]: t for t in build_profile([
        row(node="h", level=2, n=10), row(node="h", level=3, n=10),
        row(node="c", label="Counterclaim", cats=(1, 2, 3), level=2, n=10),
        row(node="c", label="Counterclaim", cats=(1, 2, 3), level=3, n=10),
    ])}
    assert out["Overall quality"]["mean"] == 2.5
    assert out["Counterclaim"]["mean"] == 2.5
    # Same mean, opposite standing.
    assert out["Overall quality"]["position"] == 0.3
    assert out["Counterclaim"]["position"] == 0.75


def test_the_weakest_trait_comes_first():
    """The order a teacher reads it in. A page that sorts alphabetically makes them do the
    comparison the page exists to do for them."""
    labels = [t["label"] for t in build_profile([
        row(node="a", label="Strong trait", level=5, n=10),
        row(node="b", label="Weak trait", level=2, n=10),
        row(node="c", label="Middling trait", level=3, n=10),
    ])]
    assert labels == ["Weak trait", "Middling trait", "Strong trait"]


def test_a_trait_nobody_could_judge_sorts_last_and_carries_no_mean():
    """Not a zero. A trait where every paper abstained is not a trait the class scored badly on,
    and a null sorted to the top would read as a floor."""
    out = build_profile([
        row(node="a", label="Scored", level=2, n=10),
        row(node="b", label="Unjudged", cats=(1, 2, 3), status="abstained", level=None,
            reason="element_not_present", n=10),
    ])
    assert [t["label"] for t in out] == ["Scored", "Unjudged"]
    assert out[1]["mean"] is None and out[1]["position"] is None
    assert out[1]["unjudged"] == 10


def test_what_could_not_be_judged_sits_beside_the_levels():
    """A trait where a third of the class abstained is not a trait the class is average at.
    Dropping those counts is how "we could not tell" reads as a middling score."""
    t = build_profile([
        row(node="c", label="Counterclaim", cats=(1, 2, 3), level=3, n=5),
        row(node="c", label="Counterclaim", cats=(1, 2, 3), status="abstained", level=None,
            reason="element_not_present", n=15),
    ])[0]
    assert t["scored"] == 5
    assert t["unjudged"] == 15
    assert t["unjudged_reasons"] == {"element_not_present": 15}


def test_the_reason_is_kept_because_the_two_absences_are_different():
    """"The writing contains no counterclaim" is a fact about the writing. "No span survived
    verification" is a fact about our reading of it. A teacher acts on the first and an engineer
    on the second."""
    t = build_profile([
        row(node="c", cats=(1, 2, 3), status="abstained", level=None,
            reason="element_not_present", n=4),
        row(node="c", cats=(1, 2, 3), status="no_verified_evidence", level=None,
            reason="no_spans_proposed", n=3),
    ])[0]
    assert t["unjudged_reasons"] == {"element_not_present": 4, "no_spans_proposed": 3}


def test_every_level_of_the_scale_is_present_including_the_empty_ones():
    """A level that vanishes at zero is how a teacher stops noticing that nobody reached the top —
    the same argument as the manifest gate showing all five counts."""
    t = build_profile([row(level=3, n=8)])[0]
    assert set(t["levels"]) == {"1", "2", "3", "4", "5", "6"}
    assert t["levels"]["6"] == 0
    assert t["at_highest"] == 0
    assert t["at_lowest"] == 0


def test_the_ends_of_the_scale_are_named_not_only_counted():
    """"Nine of twenty-eight are at the bottom" is the sentence a teacher acts on, and it is
    invisible in a mean."""
    t = build_profile([row(level=1, n=9), row(level=6, n=2), row(level=3, n=17)])[0]
    assert t["at_lowest"] == 9 and t["at_highest"] == 2


def test_no_number_spans_traits_for_a_student():
    """The restraint this page keeps. A per-student figure across traits ranks students, and a
    lesson-planning page would become a leaderboard with a different label on it."""
    t = build_profile([row(level=4, n=28)])[0]
    for banned in ("student", "students", "student_id", "per_student", "ranking"):
        assert banned not in t, f"the profile carries {banned!r}"
