"""Publication goes through the linter, and the demo cannot squat on a real identifier.

The linter was eight fully-tested rules called by nothing but its own test file, and the first
end-to-end run published six node versions without any of them running. A rule that is not on the
path is not a rule — so these tests are about the WIRING, not the rules.
"""
from __future__ import annotations

import inspect

from registry import seed_demo
from registry.lint import BLOCKING, Registry, blocks_publication, lint

ID_CONSTANTS = ("TASK_ID", "SITE_ID", "DRAFT_SITE_ID", "CONFIG_KEY", "CONFIG_ID")


def test_every_seeded_identifier_carries_the_prefix():
    """A node identifier is issued once and never recycled. A demo that squatted on one of the
    real Free Speech identifiers would poison the registry permanently, and --purge deletes by
    prefix, so an escaped id would be both created and left behind."""
    for name in ID_CONSTANTS:
        value = getattr(seed_demo, name)
        assert value.startswith(seed_demo.PREFIX), f"{name}={value!r} would survive --purge"


def test_the_fixture_nodes_are_prefixed_by_the_seed_not_by_the_fixture():
    for node in seed_demo.load()["nodes"]:
        assert not node["id"].startswith(seed_demo.PREFIX), (
            "a pre-prefixed id would be double-prefixed and stop matching anything")


def test_versions_are_inserted_as_draft_and_published_only_after_the_lint():
    """The order is the whole point: insert as draft, read the registry BACK from the database,
    lint what is actually stored, then publish. Linting the in-memory intent would check what we
    meant to write rather than what is there."""
    src = inspect.getsource(seed_demo.seed)
    assert "'draft'" in src
    assert "'published'" not in src.split("findings = lint(")[0], (
        "something publishes before the lint runs")
    assert src.index("findings = lint(") < src.index("status = 'published'")
    assert "if not blocked" in src


def test_a_blocking_finding_leaves_the_drafts_in_place():
    """A draft can be fixed; a published version cannot. Refusing publication and keeping the
    drafts is the useful failure state."""
    src = inspect.getsource(seed_demo.seed)
    assert "published = 0" in src


def test_the_demo_nodes_are_diagnostic_only():
    """`anchor` carries the linking between tasks. A demo node claiming to be one would put
    synthetic papers into the calibration path, which is where they must never be."""
    src = inspect.getsource(seed_demo.seed)
    assert "'diagnostic_only'" in src
    assert "'anchor'" not in src


def test_the_prompt_fingerprint_is_not_invented_here():
    """It belongs to `scoring`, which registry may not import. Passing it in is not a workaround
    for the boundary rule — recording the pipeline's identity is what promotion IS."""
    src = inspect.getsource(seed_demo)
    assert "prompt_versions: dict" in src or "prompt_versions)" in src
    assert "from scoring" not in src and "import scoring" not in src


# ------------------------------------------------------------------ the fixture actually lints


def _registry_from_fixture(**overrides) -> Registry:
    nodes, versions, site_nodes = [], [], []
    for ordinal, node in enumerate(seed_demo.load()["nodes"]):
        nid = f"{seed_demo.PREFIX}{node['id']}"
        cats = sorted(float(k) if "." in k else int(k) for k in node["levels"])
        nodes.append({"node_id": nid, "standard_code": f"DEMO.{node['id'].upper()}",
                      "criterion_label": node["name"], "grade_band": "11-12",
                      "scale_categories": cats, "kind": "diagnostic_only"})
        versions.append({"node_version_id": f"{nid}-v1", "node_id": nid, "version": 1,
                         "descriptors": node["levels"], "status": "draft"})
        site_nodes.append({"site_id": seed_demo.SITE_ID, "node_id": nid, "ordinal": ordinal})
    base = dict(
        nodes=nodes, versions=versions,
        tasks=[{"task_id": seed_demo.TASK_ID, "module_key": "demo-free-speech",
                "name": "Culminating op-ed", "ordinal": 1, "grade_band": "11-12"}],
        sites=[{"site_id": seed_demo.SITE_ID, "task_id": seed_demo.TASK_ID,
                "iteration": "final", "is_measurement_occasion": True}],
        site_nodes=site_nodes)
    base.update(overrides)
    return Registry(**base)


def test_the_demo_rubric_passes_the_blocking_rules():
    """If it did not, the seed would refuse to publish and the end-to-end run would have nothing
    to score. Better to find that here than in Cloud Shell."""
    findings = lint(_registry_from_fixture())
    blocking = [str(f) for f in findings if f.severity == BLOCKING]
    assert not blocking, blocking
    assert not blocks_publication(findings)


def test_a_broken_scale_in_the_fixture_would_actually_block():
    """A guard on the guard: the test above is only meaningful if the linter can fail here."""
    r = _registry_from_fixture()
    r.nodes[0]["scale_categories"] = [3]
    assert blocks_publication(lint(r))
