"""Publication goes through the linter, and an identifier means nothing.

Two things this file is about. The linter was a dozen fully-tested rules called by nothing but its
own test file, and the first end-to-end run published six node versions without one of them
running — so these tests are about the WIRING, not the rules.

And identifiers. `demo-ci` made one string carry identity, a human-readable name, and a lifecycle
flag at once, and `--purge` matched on the lifecycle part, which made deletion depend on identity.
What follows asserts the separation rather than the old prefix: a UUID that means nothing, a
`criterion_label` a person can read, an `external_ref` holding the publisher's own short code, and
a purge that walks the rubric graph.
"""
from __future__ import annotations

import inspect
import re

from registry import seed_demo
from registry.lint import ADVISORY, BLOCKING, Registry, blocks_publication, lint

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Words that describe a row's LIFECYCLE. None belongs in something that has to outlive the fact it
# records — content gets promoted, fixtures become real, and an identifier cannot follow.
LIFECYCLE_WORDS = ("demo", "test", "temp", "tmp", "sample", "dummy", "fake")


def test_every_reference_identifier_is_a_uuid():
    """Rubric, skill and trait identifiers are issued once and never recycled, and every historical
    score is stamped with one. A value someone can type by hand is one someone can type twice."""
    for name in ("RUBRIC_ID", "SKILL_ID", "CONFIG_ID"):
        assert UUID_RE.match(getattr(seed_demo, name)), f"{name} is not a UUID"
    for node in seed_demo.load()["nodes"]:
        assert UUID_RE.match(seed_demo.trait_id(node["id"]))


def test_no_identifier_carries_a_lifecycle_word():
    """`demo-` was a lifecycle fact wedged into an identity. The fact changes; the identity cannot."""
    ids = [seed_demo.RUBRIC_ID, seed_demo.SKILL_ID, seed_demo.CONFIG_ID, seed_demo.TASK_ID,
           seed_demo.SITE_ID, seed_demo.DRAFT_SITE_ID, seed_demo.CONFIG_KEY]
    ids += [seed_demo.trait_id(n["id"]) for n in seed_demo.load()["nodes"]]
    offenders = [i for i in ids if any(w in i.lower() for w in LIFECYCLE_WORDS)]
    assert not offenders, f"identifiers carrying a lifecycle word: {offenders}"


def test_a_trait_identifier_is_stable_across_runs():
    """Derived rather than random, so re-seeding is idempotent and a trait keeps its identifier.
    Real content does not work this way — a person issues one, once."""
    assert seed_demo.trait_id("ci") == seed_demo.trait_id("ci")
    assert seed_demo.trait_id("ci") != seed_demo.trait_id("ev")


def test_the_readable_name_and_the_publishers_code_are_separate_columns():
    """`ci` was an identifier standing in for a name. The name is what a person reads; the short
    code belongs to CoreTools and is a reference, never an identity."""
    src = inspect.getsource(seed_demo.seed)
    assert '"label": node["name"]' in src, "criterion_label must carry the readable name"
    assert '"ref": node["id"]' in src, "external_ref must carry the publisher's own code"


# ------------------------------------------------------------------ the wiring


def test_versions_are_inserted_as_draft_and_published_only_after_the_lint():
    """Insert as draft, read the registry BACK from the database, lint what is actually stored,
    then publish. Linting the in-memory intent would check what we meant to write."""
    src = inspect.getsource(seed_demo.seed)
    assert "'draft'" in src
    assert "'published'" not in src.split("findings = lint(")[0], (
        "something publishes before the lint runs")
    assert src.index("findings = lint(") < src.index("status = 'published'")
    assert "not blocked" in src, "publication is not gated on the lint result"


def test_an_acknowledged_registry_does_not_report_as_a_spotless_one():
    """The first acknowledgment cleared four findings and the output became indistinguishable from
    a registry that never had any. Storing a reason and then not showing it is the check being
    skipped with extra steps, so the seed lints twice and names the difference."""
    src = inspect.getsource(seed_demo.seed)
    assert "acknowledgments={}" in src
    assert "cleared" in src and '"acknowledged"' in src
    assert src.index("findings = lint(") < src.index("cleared = ")


def test_the_fixture_nodes_are_diagnostic_only():
    """`anchor` carries the linking between tasks. A fixture node claiming to be one would put
    synthetic papers into the calibration path, which is where they must never be."""
    src = inspect.getsource(seed_demo.seed)
    assert "'diagnostic_only'" in src
    assert "'anchor'" not in src


def test_a_clause_split_nobody_made_is_recorded_as_whole():
    """`derivation` separates what a standards document says from what a person decided it meant.
    The fixture does not split WHST.11-12.1, so it must not claim somebody did."""
    src = inspect.getsource(seed_demo.seed)
    assert "'whole'" in src and "'clause'" not in src


def test_the_prompt_fingerprint_is_not_invented_here():
    """It belongs to `scoring`, which registry may not import. Recording the pipeline's identity is
    what promotion IS."""
    src = inspect.getsource(seed_demo)
    assert "from scoring" not in src and "import scoring" not in src


# ------------------------------------------------------------------ the purge


def test_the_purge_walks_the_rubric_graph_rather_than_matching_a_name():
    src = inspect.getsource(seed_demo.purge)
    assert "rubric_id = :r" in src
    assert "LIKE" not in src, "a name match is what the UUIDs were supposed to remove"


def test_the_purge_keeps_a_trait_another_rubric_claims():
    """The many-to-many taken seriously. Deleting a trait because this fixture introduced it would
    destroy an identifier some other rubric had declared common with it."""
    src = inspect.getsource(seed_demo.purge)
    assert "still_claimed" in src and "orphans" in src
    assert src.index("still_claimed") < src.index("DELETE FROM registry_node WHERE")


# ------------------------------------------------------------------ the fixture actually lints


def _registry_from_fixture(**overrides) -> Registry:
    nodes, versions, traits = [], [], []
    for ordinal, node in enumerate(seed_demo.load()["nodes"]):
        nid = seed_demo.trait_id(node["id"])
        cats = sorted(float(k) if "." in k else int(k) for k in node["levels"])
        nodes.append({"node_id": nid, "standard_code": seed_demo.STANDARD,
                      "criterion_label": node["name"], "grade_band": seed_demo.GRADE_BAND,
                      "scale_categories": cats, "kind": "diagnostic_only",
                      "external_ref": node["id"]})
        versions.append({"node_version_id": f"{nid}:1", "node_id": nid, "version": 1,
                         "descriptors": node["levels"], "status": "draft"})
        traits.append({"rubric_id": seed_demo.RUBRIC_ID, "node_id": nid, "ordinal": ordinal})
    base = dict(
        skills=[{"skill_id": seed_demo.SKILL_ID, "standard_code": seed_demo.STANDARD,
                 "sub_code": None, "statement": "Write arguments.", "derivation": "whole",
                 "grade_band": seed_demo.GRADE_BAND, "rubric_id": seed_demo.RUBRIC_ID}],
        rubrics=[{"rubric_id": seed_demo.RUBRIC_ID, "name": seed_demo.RUBRIC_NAME,
                  "publisher": seed_demo.PUBLISHER, "grade_band": seed_demo.GRADE_BAND,
                  "status": "published"}],
        rubric_traits=traits, nodes=nodes, versions=versions,
        tasks=[{"task_id": seed_demo.TASK_ID, "module_key": "free-speech",
                "name": "Culminating op-ed", "ordinal": 1,
                "grade_band": seed_demo.GRADE_BAND}],
        sites=[{"site_id": seed_demo.SITE_ID, "task_id": seed_demo.TASK_ID,
                "iteration": "final", "is_measurement_occasion": True,
                "rubric_id": seed_demo.RUBRIC_ID}],
        site_nodes=[{"site_id": seed_demo.SITE_ID, "node_id": n["node_id"], "ordinal": i}
                    for i, n in enumerate(nodes)])
    base.update(overrides)
    return Registry(**base)


def test_the_fixture_rubric_passes_the_blocking_rules():
    blocking = [str(f) for f in lint(_registry_from_fixture()) if f.severity == BLOCKING]
    assert not blocking, blocking


def test_a_broken_scale_would_actually_block():
    """A guard on the guard: the test above is only meaningful if the linter can fail here."""
    r = _registry_from_fixture()
    r.nodes[0]["scale_categories"] = [3]
    assert blocks_publication(lint(r))


# ------------------------------------------------------------------ the new rules


def test_a_published_rubric_with_no_traits_blocks():
    """A site pointing at it resolves to an empty trait set, and the artifact reaches `scored`
    having measured nobody."""
    r = _registry_from_fixture(rubric_traits=[])
    assert "rubric_has_traits" in {f.rule for f in lint(r)}
    assert blocks_publication(lint(r))


def test_a_trait_in_a_rubric_of_another_grade_band_blocks():
    """The band is part of the trait's identity, so one of the two is wrong and nothing downstream
    can recover which."""
    r = _registry_from_fixture()
    r.rubrics[0]["grade_band"] = "6-8"
    assert "rubric_trait_grade_band" in {f.rule for f in lint(r)}
    assert blocks_publication(lint(r))


def test_a_trait_used_across_two_standards_is_advisory_not_blocking():
    """Reusing a trait identifier is how commonality gets declared, and a trait shared across
    standards may be exactly the anchor that links them. It may equally be somebody reaching for a
    trait that looked close enough. The linter cannot tell those apart, so it refuses to let the
    question go unasked rather than deciding it."""
    r = _registry_from_fixture()
    other = "11111111-2222-3333-4444-555555555555"
    r.rubrics.append({"rubric_id": other, "name": "Another", "publisher": "x",
                      "grade_band": seed_demo.GRADE_BAND, "status": "published"})
    r.skills.append({"skill_id": "66666666-7777-8888-9999-aaaaaaaaaaaa",
                     "standard_code": "RH.11-12.6", "sub_code": "a", "statement": "s",
                     "derivation": "lettered", "grade_band": seed_demo.GRADE_BAND,
                     "rubric_id": other})
    shared = r.nodes[0]["node_id"]
    r.rubric_traits.append({"rubric_id": other, "node_id": shared, "ordinal": 0})

    findings = lint(r)
    crossing = [f for f in findings if f.rule == "trait_crosses_standards"]
    assert crossing and crossing[0].severity == ADVISORY
    assert crossing[0].subject == shared
    assert not blocks_publication(findings)


def test_a_skill_with_no_rubric_is_advisory_and_says_it_is_unmeasured():
    """Taught and not scored is legitimate and common — the review console says so outright. The
    alternative to an advisory is a coverage table that quietly counts it as covered."""
    r = _registry_from_fixture()
    r.skills[0]["rubric_id"] = None
    findings = [f for f in lint(r) if f.rule == "skill_unscored"]
    assert findings and findings[0].severity == ADVISORY
    assert "nothing about it is measured" in findings[0].message
