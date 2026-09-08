"""PERSUADE's instruments, transcribed rather than reconstructed — and what they imply.

Anchor calibration asks how severe our rater is against a known standard. Show the model
descriptors we wrote while the humans used descriptors PERSUADE wrote, and the estimated severity
confounds "our rater is harsher" with "our rubric says something different", with no way to
separate them afterwards and no sign that anything is wrong.

Two findings from reading the real forms drive most of this file: there are TWO holistic rubrics,
and conventions is inside the holistic construct.
"""
from __future__ import annotations

from registry.persuade_rubrics import (ADAPTED, CONVENTIONS_IN_CONSTRUCT,
                                       EFFECTIVENESS_SCALE, EFFECTIVENESS_WORDS, HOLISTIC_SCALE,
                                       TRANSCRIBED, all_rubrics, distinct_traits, elements,
                                       evidence_trait, holistic, node_id, rubric_id,
                                       shared_element_traits)


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


def test_the_two_holistic_traits_are_separate():
    """The whole scale is described differently on each form, so these are two constructs."""
    assert (holistic("independent")["traits"][0]["node_id"]
            != holistic("text_dependent")["traits"][0]["node_id"])


# ------------------------------------------------------------------ six shared, two evidence

def test_six_elements_are_shared_between_the_two_element_rubrics():
    """The load-bearing decision, and the only mechanism that can place both halves of PERSUADE on
    one metric. A counterclaim is a counterclaim whether or not a source text was supplied; own
    these to a rubric each and the halves float apart with no arithmetic that could bring them
    together."""
    ind = {t["node_id"] for t in elements("independent")["traits"]}
    dep = {t["node_id"] for t in elements("text_dependent")["traits"]}
    assert len(ind & dep) == 6
    shared_labels = {t["criterion_label"] for t in shared_element_traits()}
    assert shared_labels == {"Lead", "Position", "Claim", "Counterclaim", "Rebuttal",
                             "Concluding summary"}


def test_evidence_is_the_one_element_that_splits():
    """The same exception the holistic forms make: a text-dependent task requires the evidence to
    come from the source. Different construct, different trait."""
    ind, dep = evidence_trait("independent"), evidence_trait("text_dependent")
    assert ind["node_id"] != dep["node_id"]
    assert "taken from the source text" in dep["descriptors"]["3"]
    assert "taken from the source text" not in ind["descriptors"]["3"]


def test_ten_distinct_traits_across_four_rubrics():
    """Two holistic, six shared elements, two evidence."""
    assert len(all_rubrics()) == 4
    assert len(distinct_traits()) == 10
    # Fourteen trait slots over ten identifiers: the six shared ones are counted twice.
    assert sum(len(r["traits"]) for r in all_rubrics()) == 16


def test_the_sourced_evidence_descriptors_are_marked_as_adapted():
    """The rating form has ONE evidence descriptor set, written without a source requirement. The
    sourced trait adds the clause following the holistic form's own pattern — authored, not
    transcribed. A descriptor nobody can trace is one that will later be cited as PERSUADE's."""
    assert evidence_trait("text_dependent")["provenance"] == ADAPTED
    assert evidence_trait("independent")["provenance"] == TRANSCRIBED
    for t in shared_element_traits():
        assert t["provenance"] == TRANSCRIBED
    for task in ("independent", "text_dependent"):
        assert holistic(task)["traits"][0]["provenance"] == TRANSCRIBED


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
    for trait in distinct_traits().values():
        if trait["standard_code"] != "PERSUADE.ELEMENT":
            continue
        assert trait["conventions_in_construct"] is False
        assert trait["node_id"] not in CONVENTIONS_IN_CONSTRUCT
        for d in trait["descriptors"].values():
            assert "grammar" not in d and "mechanics" not in d


def test_the_conventions_set_is_derived_from_the_traits():
    """Computed at import from the traits themselves, so a new node cannot be added without
    landing on the right side of it — the exclusion must not depend on somebody remembering."""
    assert CONVENTIONS_IN_CONSTRUCT == frozenset(
        nid for nid, t in distinct_traits().items() if t["conventions_in_construct"])
    assert len(CONVENTIONS_IN_CONSTRUCT) == 2


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
    for task in ("independent", "text_dependent"):
        traits = elements(task)["traits"]
        assert len(traits) == 7
        for t in traits:
            assert set(t["descriptors"]) == {"1", "2", "3"}


def test_the_seven_elements_are_the_ones_the_rubric_lists():
    labels = {t["criterion_label"] for t in elements("independent")["traits"]}
    assert labels == {"Lead", "Position", "Claim", "Counterclaim", "Rebuttal", "Evidence",
                      "Concluding summary"}


def test_the_element_traits_match_the_discourse_types_the_corpus_carries():
    """The corpus has 9,534 counterclaim spans and 7,217 rebuttal spans. The rubric's elements and
    the corpus's segmentation have to name the same things or a model score cannot be attached to
    a span."""
    corpus_types = {"Lead", "Position", "Claim", "Counterclaim", "Rebuttal", "Evidence",
                    "Concluding Statement"}
    labels = {t["criterion_label"] for t in elements("independent")["traits"]}
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


def test_all_four_rubrics_are_registered():
    rubrics = all_rubrics()
    assert len(rubrics) == 4
    assert {len(r["traits"]) for r in rubrics} == {1, 7}
