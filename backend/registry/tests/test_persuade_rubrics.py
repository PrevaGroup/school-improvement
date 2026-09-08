"""PERSUADE's instruments, transcribed rather than reconstructed — and what they imply.

Anchor calibration asks how severe our rater is against a known standard. Show the model
descriptors we wrote while the humans used descriptors PERSUADE wrote, and the estimated severity
confounds "our rater is harsher" with "our rubric says something different", with no way to
separate them afterwards and no sign that anything is wrong.

Two findings from reading the real forms drive most of this file: there are TWO holistic rubrics,
and conventions is inside the holistic construct.
"""
from __future__ import annotations

from registry.persuade_rubrics import (CONVENTIONS_IN_CONSTRUCT, EFFECTIVENESS_SCALE,
                                       EFFECTIVENESS_WORDS, HOLISTIC_SCALE, all_rubrics,
                                       effectiveness, holistic, node_id, rubric_id)


# ------------------------------------------------------------------ two rubrics, not one

def test_independent_and_text_dependent_are_separate_rubrics():
    """Separate rating forms, and the corpus splits almost evenly between them. A system that
    could hold only one rubric would have had to pretend otherwise — which is the defect the
    many-rubric refactor existed to fix, arriving as real data for the first time."""
    ind, dep = holistic("independent"), holistic("text_dependent")
    assert ind["rubric_id"] != dep["rubric_id"]
    assert ind["traits"][0]["node_id"] != dep["traits"][0]["node_id"]


def test_the_difference_between_them_is_the_source_text_requirement():
    """The only textual difference, and it is a difference of construct: the text-dependent form
    requires the evidence to come from the source text."""
    ind = holistic("independent")["traits"][0]["descriptors"]
    dep = holistic("text_dependent")["traits"][0]["descriptors"]
    for k in ("1", "2", "3", "4", "5", "6"):
        if k == "1":
            continue          # score 1 is identical on both forms
        assert "taken from the source text" in dep[k], k
        assert "taken from the source text" not in ind[k], k


def test_they_do_not_share_a_trait():
    """Sharing a trait is how this registry declares that two rubrics measure one thing, and it is
    the only mechanism that could place both halves of PERSUADE on one metric. That is a product
    manager's judgment, not a transcription decision, so it is not made here."""
    assert (holistic("independent")["traits"][0]["node_id"]
            != holistic("text_dependent")["traits"][0]["node_id"])


def test_an_unknown_task_form_is_refused():
    import pytest

    with pytest.raises(ValueError, match="unknown PERSUADE task form"):
        holistic("whatever")


# ------------------------------------------------------------------ conventions is in the construct

def test_every_holistic_descriptor_names_grammar_usage_and_mechanics():
    """From "free of most errors" at 6 to "pervasive errors ... that persistently interfere with
    meaning" at 1. Conventions is part of what this scale measures."""
    for task in ("independent", "text_dependent"):
        for k, d in holistic(task)["traits"][0]["descriptors"].items():
            assert "grammar" in d and "mechanics" in d, f"{task} score {k}"


def test_the_holistic_nodes_are_marked_as_including_conventions():
    """So the exclusion from stop condition 2 is a property of the node rather than something a
    person has to remember. Adding conventions errors SHOULD move a PERSUADE holistic score, and a
    matched-pairs trigger here would be reporting the instrument rather than a defect."""
    for task in ("independent", "text_dependent"):
        trait = holistic(task)["traits"][0]
        assert trait["conventions_in_construct"] is True
        assert trait["node_id"] in CONVENTIONS_IN_CONSTRUCT


def test_the_element_rubric_does_not_include_conventions():
    """Every element descriptor is about argumentative function. Matched-pairs testing is
    legitimate against these nodes and not against the holistic ones."""
    for trait in effectiveness()["traits"]:
        assert trait["conventions_in_construct"] is False
        assert trait["node_id"] not in CONVENTIONS_IN_CONSTRUCT
        for d in trait["descriptors"].values():
            assert "grammar" not in d and "mechanics" not in d


# ------------------------------------------------------------------ the scales

def test_the_holistic_scale_is_one_to_six():
    assert HOLISTIC_SCALE == [1, 2, 3, 4, 5, 6]
    for task in ("independent", "text_dependent"):
        assert set(holistic(task)["traits"][0]["descriptors"]) == {"1", "2", "3", "4", "5", "6"}


def test_the_effectiveness_words_map_to_ordered_numbers():
    """The rubric gives three levels with no numbers. The mapping is recorded rather than assumed,
    because a reader meeting a "2" later has no way to recover which word it was — and the
    direction matters: higher must mean better, or every severity sign inverts."""
    assert EFFECTIVENESS_SCALE == [1, 2, 3]
    assert EFFECTIVENESS_WORDS == {3: "Effective", 2: "Adequate", 1: "Ineffective"}


def test_every_element_has_all_three_levels():
    traits = effectiveness()["traits"]
    assert len(traits) == 7
    for t in traits:
        assert set(t["descriptors"]) == {"1", "2", "3"}


def test_the_seven_elements_are_the_ones_the_rubric_lists():
    labels = {t["criterion_label"] for t in effectiveness()["traits"]}
    assert labels == {"Lead", "Position", "Claim", "Counterclaim", "Rebuttal", "Evidence",
                      "Concluding summary"}


def test_the_element_traits_match_the_discourse_types_the_corpus_carries():
    """The corpus has 9,534 counterclaim spans and 7,217 rebuttal spans. The rubric's elements and
    the corpus's segmentation have to name the same things or a model score cannot be attached to
    a span."""
    corpus_types = {"Lead", "Position", "Claim", "Counterclaim", "Rebuttal", "Evidence",
                    "Concluding Statement"}
    labels = {t["criterion_label"] for t in effectiveness()["traits"]}
    # One name differs between the two documents: the corpus calls it "Concluding Statement", the
    # rubric "Concluding summary". Recorded here so the join is written knowingly rather than
    # discovered as an empty result.
    assert labels - corpus_types == {"Concluding summary"}
    assert corpus_types - labels == {"Concluding Statement"}


# ------------------------------------------------------------------ identifiers

def test_identifiers_are_derived_so_reseeding_is_idempotent():
    """A rubric that has been scored against must keep its identity across a reload, or every
    score stamped with the old id points at a row that no longer exists."""
    assert rubric_id("x") == rubric_id("x")
    assert node_id("x") != node_id("y")
    assert rubric_id("x") != node_id("x")


def test_every_identifier_is_a_uuid():
    """The registry's CHECK requires it: an identifier issued once and never recycled should not
    be typeable by accident."""
    import re

    pat = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    for r in all_rubrics():
        assert pat.match(r["rubric_id"])
        for t in r["traits"]:
            assert pat.match(t["node_id"])


def test_the_standard_code_does_not_invent_an_alignment():
    """PERSUADE's holistic scale is its own instrument. Writing a CCSS code here would assert a
    mapping nobody made, and it would then be joined on."""
    for r in all_rubrics():
        for t in r["traits"]:
            assert t["standard_code"].startswith("PERSUADE.")


def test_the_publisher_is_recorded():
    """Two rubrics with the same name from different publishers are two rubrics, and it is often
    the only thing that tells them apart."""
    for r in all_rubrics():
        assert "PERSUADE" in r["publisher"]


def test_all_three_instruments_are_registered():
    rubrics = all_rubrics()
    assert len(rubrics) == 3
    assert sum(len(r["traits"]) for r in rubrics) == 1 + 1 + 7
