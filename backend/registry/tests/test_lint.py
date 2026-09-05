"""The linter, against the defects the construct audit found by hand.

Each blocking rule gets a case drawn from the real finding it generalises, so a future edit that
weakens a rule fails with a message naming the thing that would slip through.
"""
from __future__ import annotations

import pytest

from registry.lint import (ADVISORY, BLOCKING, Registry, blocks_publication, lint)


def node(node_id="ci", standard="WHST.11-12.1a", band="11-12", cats=(1, 2, 3, 4), kind="anchor",
         label="Controlling idea"):
    return {"node_id": node_id, "standard_code": standard, "grade_band": band,
            "scale_categories": list(cats), "kind": kind, "criterion_label": label}


def version(vid="v1", node_id="ci", n=1, descriptors=None, status="published", ack=None):
    return {"node_version_id": vid, "node_id": node_id, "version": n,
            "descriptors": descriptors or {"1": "a", "2": "b", "3": "c", "4": "d"},
            "status": status, "construct_unchanged_ack": ack}


def task(task_id="fs-10", module="freespeech", standards=None, band="11-12"):
    return {"task_id": task_id, "module_key": module, "name": "op-ed",
            "standards": standards or [], "grade_band": band}


def site(site_id="s1", task_id="fs-10", iteration="final", occasion=True):
    return {"site_id": site_id, "task_id": task_id, "iteration": iteration,
            "is_measurement_occasion": occasion}


def rules_hit(findings):
    return {f.rule for f in findings}


# --------------------------------------------------------------------------- #
# Blocking
# --------------------------------------------------------------------------- #
def test_one_identifier_two_scales_is_blocking():
    """A difference in category count is evidence two constructs were drawn. The same identifier
    cannot sit on both."""
    r = Registry(nodes=[node(cats=(1, 2, 3, 4)), node(cats=(1, 2, 3))])
    f = lint(r)
    assert "identifier_integrity" in rules_hit(f)
    assert blocks_publication(f)
    assert "scale_categories" in next(x for x in f if x.rule == "identifier_integrity").message


def test_one_identifier_two_grade_bands_is_blocking():
    r = Registry(nodes=[node(band="11-12"), node(band="9-12")])
    assert "identifier_integrity" in rules_hit(lint(r))


def test_differing_scales_across_DIFFERENT_nodes_is_not_flagged():
    """Six structures across seven instruments is not an inconsistency — there was never one thing
    they were being inconsistent about. Flagging it would be flagging the data for being what it
    is."""
    r = Registry(nodes=[node("ci", cats=(1, 2, 3, 4)),
                        node("persuade_ev", cats=(1, 2, 3)),
                        node("sbac_conv", cats=(0, 1, 2))])
    assert "identifier_integrity" not in rules_hit(lint(r))
    assert not blocks_publication(lint(r))


@pytest.mark.parametrize("cats,why", [
    ([], "undeclared"),
    ([3], "single category"),
    ([1, 3, 2], "out of order"),
])
def test_unfittable_scale_is_blocking(cats, why):
    r = Registry(nodes=[node(cats=cats)])
    assert "scale_declared" in rules_hit(lint(r)), why


def test_strand_substitution_is_blocking():
    """The crosswalk found this three times: RI standing in for RH. Single-text rhetoric replacing
    cross-author evidentiary reasoning — a construct error, not a coding one."""
    r = Registry(
        nodes=[node("pov", standard="RI.11-12.6", label="point of view")],
        tasks=[task(standards=["RH.11-12.6", "D2.Civ.4.9-12"])],
        sites=[site()],
        site_nodes=[{"site_id": "s1", "node_id": "pov"}],
    )
    f = lint(r)
    assert "strand_substitution" in rules_hit(f)
    assert blocks_publication(f)


def test_matching_strand_is_not_flagged():
    r = Registry(
        nodes=[node("pov", standard="RH.11-12.6")],
        tasks=[task(standards=["RH.11-12.6"])],
        sites=[site()], site_nodes=[{"site_id": "s1", "node_id": "pov"}])
    assert "strand_substitution" not in rules_hit(lint(r))


def test_w_whst_swap_is_advisory_not_blocking():
    """The asymmetry IS the finding. Reading-side strands diverge materially at Anchor 6, so a
    substitution is a construct error; W and WHST are near-verbatim, so the same swap is harmless.
    Flattening them to one severity would discard the evidence that a generic RI/RL rubric library
    exists and an RH one does not."""
    r = Registry(
        nodes=[node("ci", standard="W.11-12.1a")],
        tasks=[task(standards=["WHST.11-12.1a"])],
        sites=[site()], site_nodes=[{"site_id": "s1", "node_id": "ci"}])
    f = lint(r)
    assert "strand_substitution" in rules_hit(f)
    assert not blocks_publication(f), "the writing-side swap must not block"


def test_missing_anchor_at_a_measurement_occasion_is_blocking():
    """A linking claim rests on the anchors being present throughout."""
    r = Registry(
        nodes=[node("ci", kind="anchor"), node("ev", kind="anchor")],
        tasks=[task()], sites=[site()],
        site_nodes=[{"site_id": "s1", "node_id": "ci"}],
        linking_modules=["freespeech"])
    f = lint(r)
    assert "anchor_coverage" in rules_hit(f)
    assert "ev" in next(x for x in f if x.rule == "anchor_coverage").message


def test_a_draft_site_does_not_need_full_anchor_coverage():
    """Only occasions carry the linking claim; a draft is scored and is not the occasion."""
    r = Registry(
        nodes=[node("ci", kind="anchor"), node("ev", kind="anchor")],
        tasks=[task()], sites=[site(iteration="draft", occasion=False)],
        site_nodes=[{"site_id": "s1", "node_id": "ci"}],
        linking_modules=["freespeech"])
    assert "anchor_coverage" not in rules_hit(lint(r))


def test_descriptor_change_without_acknowledgment_is_blocking():
    """The edit either clarified the construct or replaced it. Only a person can say which — the
    linter refuses to let the question go unasked."""
    r = Registry(nodes=[node()], versions=[
        version("v1", n=1, descriptors={"1": "old"}, status="published"),
        version("v2", n=2, descriptors={"1": "materially different"}, status="draft")])
    f = lint(r)
    assert "descriptor_change_ack" in rules_hit(f)
    assert "new node identifier" in next(
        x for x in f if x.rule == "descriptor_change_ack").message


def test_descriptor_change_with_acknowledgment_passes():
    r = Registry(nodes=[node()], versions=[
        version("v1", n=1, descriptors={"1": "old"}, status="published"),
        version("v2", n=2, descriptors={"1": "clearer"}, status="draft",
                ack="reworded for clarity; construct unchanged")])
    assert "descriptor_change_ack" not in rules_hit(lint(r))


def test_identical_descriptors_need_no_acknowledgment():
    r = Registry(nodes=[node()], versions=[
        version("v1", n=1, status="published"),
        version("v2", n=2, status="draft")])
    assert "descriptor_change_ack" not in rules_hit(lint(r))


# --------------------------------------------------------------------------- #
# Advisory
# --------------------------------------------------------------------------- #
def test_taught_but_unscored_is_advisory_not_blocking():
    """The gap may be deliberate — the diagnostic channel exists for exactly this. What the linter
    refuses is for it to be silent."""
    r = Registry(
        nodes=[node("ci", label="Controlling idea")],
        tasks=[task()], sites=[site()],
        site_nodes=[{"site_id": "s1", "node_id": "ci"}],
        taught_constructs={"freespeech": ["Controlling idea", "Counterclaim", "Rebuttal"]})
    f = lint(r)
    assert "taught_but_unscored" in rules_hit(f)
    assert not blocks_publication(f)
    subjects = {x.subject for x in f if x.rule == "taught_but_unscored"}
    assert subjects == {"freespeech:Counterclaim", "freespeech:Rebuttal"}


def test_an_acknowledged_advisory_clears():
    """It clears with a recorded reason, which becomes part of the version record — so the next
    reader sees a judgment that was made rather than a check that was skipped."""
    r = Registry(
        nodes=[node("ci", label="Controlling idea")],
        tasks=[task()], sites=[site()],
        site_nodes=[{"site_id": "s1", "node_id": "ci"}],
        taught_constructs={"freespeech": ["Controlling idea", "Counterclaim"]},
        acknowledgments={"taught_but_unscored:freespeech:Counterclaim":
                         "covered by the diagnostic channel; not in the trait set by design"})
    assert "taught_but_unscored" not in rules_hit(lint(r))


def test_a_diagnostic_only_node_does_not_count_as_scoring_it():
    """Diagnostic content carries zero score contribution, so it does not close a scoring gap."""
    r = Registry(
        nodes=[node("cc", label="Counterclaim", kind="diagnostic_only")],
        tasks=[task()], sites=[site()],
        site_nodes=[{"site_id": "s1", "node_id": "cc"}],
        taught_constructs={"freespeech": ["Counterclaim"]})
    assert "taught_but_unscored" in rules_hit(lint(r))


def test_stacked_conditionals_flagged():
    """The C3 cell: three sub-judgments each prefaced 'when relevant'."""
    r = Registry(nodes=[node("con")], versions=[version("v1", "con", descriptors={
        "1": ["Identifies parts of founding documents", "Applies them", "Explains the change"]})])
    f = lint(r)
    assert "stacked_conditionals" in rules_hit(f)
    assert not blocks_publication(f)


def test_grade_band_mismatch_flagged():
    """A rubric headed '9th-12th Grade' on an 11-12 module. Grade band is part of the node
    identity, so this is a wrong value in a load-bearing key."""
    r = Registry(nodes=[node("ci", band="9-12")], tasks=[task(band="11-12")],
                 sites=[site()], site_nodes=[{"site_id": "s1", "node_id": "ci"}])
    assert "grade_band_coherence" in rules_hit(lint(r))


# --------------------------------------------------------------------------- #
# Shape of the pass
# --------------------------------------------------------------------------- #
def test_a_clean_registry_produces_nothing():
    r = Registry(
        nodes=[node("ci", kind="anchor"), node("ev", standard="RI.11-12.1", kind="anchor",
                                               label="Evidence")],
        versions=[version("v1", "ci"), version("v2", "ev")],
        tasks=[task(standards=["WHST.11-12.1a"])],
        sites=[site()],
        site_nodes=[{"site_id": "s1", "node_id": "ci"}, {"site_id": "s1", "node_id": "ev"}],
        linking_modules=["freespeech"],
        taught_constructs={"freespeech": ["Controlling idea", "Evidence"]})
    assert lint(r) == []


def test_blocking_findings_sort_first():
    r = Registry(nodes=[node(cats=[]), node("x", label="Other")],
                 tasks=[task()], sites=[site()],
                 site_nodes=[{"site_id": "s1", "node_id": "x"}],
                 taught_constructs={"freespeech": ["Counterclaim"]})
    f = lint(r)
    assert f[0].severity == BLOCKING
    assert f[-1].severity == ADVISORY
