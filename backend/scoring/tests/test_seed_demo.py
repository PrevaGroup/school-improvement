"""The demo seed must not be able to touch anything real.

The registry's central rule is that a node identifier is issued once and never recycled, because
every historical score stamped with it would otherwise become ambiguous. A demo that squatted on a
real identifier would do exactly that, permanently, and `--purge` deletes by prefix — so a single
id that escaped the prefix would be both created and left behind.

That makes "every id starts with demo-" a safety property rather than a naming convention, and it
is asserted here against the module's own constants and against the fixture it seeds from.
"""
from __future__ import annotations

import inspect

import pytest

from scoring import seed_demo
from scoring.prompts import render_scale
from scoring.score import Criterion, build_evidence_prompt

ID_CONSTANTS = ("TASK_ID", "SITE_ID", "DRAFT_SITE_ID", "SECTION_ID", "CONFIG_KEY", "CONFIG_ID",
                "RUN_ID")


def test_every_seeded_identifier_carries_the_prefix():
    for name in ID_CONSTANTS:
        value = getattr(seed_demo, name)
        assert value.startswith(seed_demo.PREFIX), f"{name}={value!r} would survive --purge"


def test_the_fixture_nodes_all_become_prefixed_ids():
    fx = seed_demo.load()
    assert fx["nodes"], "the fixture has no nodes"
    for node in fx["nodes"]:
        assert not node["id"].startswith(seed_demo.PREFIX), (
            "the fixture stores bare ids and the seed prefixes them; a pre-prefixed id would be "
            "double-prefixed and stop matching anything")


def test_the_purge_deletes_by_prefix_and_only_by_prefix():
    """A purge that matched on anything else could reach a real row."""
    src = inspect.getsource(seed_demo.purge)
    assert "LIKE :p" in src
    assert src.count('{"p": f"{PREFIX}%"}') >= 2
    assert "WHERE 1=1" not in src and "DELETE FROM registry_node\n" not in src


def test_the_demo_nodes_are_diagnostic_only():
    """`anchor` carries the linking between tasks. A demo node that claimed to be one would put
    synthetic papers into the calibration path — which is the one place they must never be."""
    src = inspect.getsource(seed_demo.seed)
    assert "'diagnostic_only'" in src
    assert "'anchor'" not in src


# ------------------------------------------------------------------ the fixture is scorable


def _criteria():
    fx = seed_demo.load()
    out = []
    for node in fx["nodes"]:
        nid = f"{seed_demo.PREFIX}{node['id']}"
        cats = sorted(float(k) if "." in k else int(k) for k in node["levels"])
        out.append(Criterion(node_id=nid, criterion_label=node["name"], categories=cats,
                             descriptors=node["levels"], node_version_id=f"{nid}-v1"))
    return out


@pytest.mark.parametrize("c", _criteria(), ids=lambda c: c.node_id)
def test_every_fixture_node_renders_its_whole_scale(c):
    """render_scale raises on a missing descriptor. Better to learn that here than four minutes
    into a Cloud Shell run that has already paid for half the calls."""
    out = render_scale(c.criterion_label, c.descriptors, c.categories)
    for cat in c.categories:
        assert f"Level {cat}:" in out


def test_a_fixture_paper_assembles_a_stage_c_prompt():
    fx = seed_demo.load()
    paper = next(iter(fx["papers"].values()))
    prompt = build_evidence_prompt(_criteria()[0], paper["text"])
    assert "<text>" in prompt and paper["text"][:40] in prompt
    assert prompt.count("CRITERION: ") == 1


def test_the_papers_are_long_enough_to_be_attempts():
    for key, paper in seed_demo.load()["papers"].items():
        assert len(paper["text"]) > 200, f"{key} would be a strange thing to demonstrate with"
