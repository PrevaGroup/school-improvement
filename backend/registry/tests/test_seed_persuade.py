"""Publishing PERSUADE's rubrics, and the ways a shared trait quietly stops being shared.

The six shared element traits are the only mechanism that can place both halves of PERSUADE on one
metric. Every failure mode here ends the same way: two identifiers where there should be one, two
scales that can never be brought together, and nothing on any screen suggesting a problem.
"""
from __future__ import annotations

import inspect

from registry import seed_persuade
from registry.persuade_rubrics import all_rubrics, distinct_traits


def _sql() -> str:
    return inspect.getsource(seed_persuade.seed)


# ------------------------------------------------------------------ the shared traits

def test_a_shared_node_is_inserted_once_and_linked_twice():
    """The node loop runs over DISTINCT traits; the rubric loop writes the join rows. Inserting a
    node per rubric would give the same construct two identifiers, and no arithmetic afterwards
    could bring the two halves of PERSUADE onto one scale."""
    src = _sql()
    node_insert = src.index("INSERT INTO registry_node ")
    trait_insert = src.index("INSERT INTO registry_rubric_trait")
    assert src.index("for t in traits.values():") < node_insert
    assert src.index("for r in rubrics:") < trait_insert
    # And the node loop is over the deduplicated mapping, not over rubric traits.
    assert "traits = distinct_traits()" in src


def test_the_six_shared_traits_get_two_join_rows_each():
    counts: dict[str, int] = {}
    for r in all_rubrics():
        for t in r["traits"]:
            counts[t["node_id"]] = counts.get(t["node_id"], 0) + 1
    shared = [n for n, c in counts.items() if c == 2]
    assert len(shared) == 6
    assert len(counts) == 10
    assert sum(counts.values()) == 16


def test_every_node_written_is_one_of_the_ten():
    """A seed that invented an eleventh identifier would produce a trait nothing scores against
    and nothing notices."""
    assert set(distinct_traits()) == {t["node_id"] for r in all_rubrics() for t in r["traits"]}


# ------------------------------------------------------------------ the linter decides

def test_versions_are_written_as_draft():
    """Publication is the linter's decision. A rubric that reached `published` without passing it
    is a rubric nobody checked, and every score written against it inherits that."""
    src = _sql()
    assert "'draft'" in src.split("INSERT INTO registry_node_version")[1][:400]


def test_nothing_is_published_when_the_linter_blocks():
    src = _sql()
    assert "if drafts and not blocked and not dry_run:" in src


def test_a_cleared_finding_is_reported_separately_from_a_clean_registry():
    """Linting twice — once with acknowledgments, once without — is what keeps "a judgment
    somebody made" distinguishable from "a check that never ran". Without it the two severity
    classes mean nothing."""
    src = _sql()
    assert "acknowledgments={}" in src
    assert "cleared_by_acknowledgment" in src


def test_a_dry_run_rolls_back():
    src = _sql()
    assert "conn.rollback()" in src
    assert "if dry_run:" in src


# ------------------------------------------------------------------ what it deliberately omits

def test_no_scoring_site_is_created():
    """A site says which iterations of a TASK are scored on which rubric. PERSUADE papers are not
    handed in against a task — no class, no iteration, no teacher. Inventing one would put anchor
    papers in the same shape as student work, and they would eventually be counted as it."""
    src = _sql()
    assert "registry_scoring_site" not in src
    assert "registry_task" not in src


def test_no_skill_is_created():
    """A skill is a claim about what a standards document says. PERSUADE's holistic scale is its
    own instrument and its elements are argumentative functions; neither is a sub-standard of
    anything, and writing one would assert an alignment nobody made."""
    assert "registry_skill" not in _sql()


def test_it_does_not_describe_itself_as_a_fixture():
    """`seed_demo` writes synthetic papers and says so in every source field. This is a published
    instrument that scored real student writing, and the anchor estimates from it are what a
    promotion decision will rest on."""
    assert "fixture" not in seed_persuade.SOURCE.lower()
    assert "CC BY 4.0" in seed_persuade.SOURCE


# ------------------------------------------------------------------ provenance survives the write

def test_provenance_is_written_onto_the_version():
    """A reader meeting these descriptors later has to be able to tell transcription from
    authoring without leaving the row — the sourced-evidence descriptors are ours, not
    PERSUADE's."""
    src = _sql()
    assert 't["provenance"]' in src
    assert "change_note" in src


def test_the_adapted_trait_is_the_only_one_that_says_adapted():
    from registry.persuade_rubrics import ADAPTED

    adapted = [t for t in distinct_traits().values() if t["provenance"] == ADAPTED]
    assert len(adapted) == 1
    assert adapted[0]["criterion_label"] == "Evidence (source-based)"
