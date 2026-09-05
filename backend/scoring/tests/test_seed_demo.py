"""The demo seed must not be able to touch anything real, and must agree with registry's half.

`--purge` deletes by prefix, so an id that escaped the prefix would be both created and left
behind. That makes "every id starts with demo-" a safety property rather than a naming convention.

The cross-file agreement test is the price of the honest duplication: `scoring.seed_demo` names a
task that `registry.seed_demo` authors, and it may not import it (modules integrate through
tables). A binding key naming a task that does not exist is the demo failing at the trait-set read
with nothing useful to say about why.
"""
from __future__ import annotations

import inspect

import pytest

from registry import seed_demo as registry_seed
from scoring import seed_demo
from scoring.prompts import render_scale
from scoring.score import Criterion, build_evidence_prompt

ID_CONSTANTS = ("RUN_ID", "SECTION_ID", "TASK_ID", "CONFIG_KEY")


def test_every_seeded_identifier_carries_the_prefix():
    for name in ID_CONSTANTS:
        value = getattr(seed_demo, name)
        assert value.startswith(seed_demo.PREFIX), f"{name}={value!r} would survive --purge"


def test_the_two_halves_of_the_demo_agree_on_the_binding():
    """The duplication is deliberate — this is what keeps it honest."""
    assert seed_demo.TASK_ID == registry_seed.TASK_ID
    assert seed_demo.CONFIG_KEY == registry_seed.CONFIG_KEY
    assert seed_demo.PREFIX == registry_seed.PREFIX


def test_the_purge_deletes_by_prefix_and_only_by_prefix():
    src = inspect.getsource(seed_demo.purge)
    assert "LIKE :p" in src
    assert src.count('{"p": f"{PREFIX}%"}') >= 2
    assert "WHERE 1=1" not in src


def test_the_purge_restores_the_append_only_trigger_even_when_the_delete_fails():
    """It disables a trigger to remove demo events. Leaving score_event mutable afterwards would
    turn a cleanup script into a silent hole in the record's central invariant."""
    src = inspect.getsource(seed_demo.purge)
    assert "finally:" in src
    assert src.index("ENABLE TRIGGER") > src.index("finally:")


# ------------------------------------------------------------------ the fixture is scorable


def _criteria():
    out = []
    for node in registry_seed.load()["nodes"]:
        nid = f"{registry_seed.PREFIX}{node['id']}"
        cats = sorted(float(k) if "." in k else int(k) for k in node["levels"])
        out.append(Criterion(node_id=nid, criterion_label=node["name"], categories=cats,
                             descriptors=node["levels"], node_version_id=f"{nid}-v1"))
    return out


@pytest.mark.parametrize("c", _criteria(), ids=lambda c: c.node_id)
def test_every_fixture_node_renders_its_whole_scale(c):
    """render_scale raises on a missing descriptor. Better to learn that here than four minutes
    into a run that has already paid for half its calls."""
    out = render_scale(c.criterion_label, c.descriptors, c.categories)
    for cat in c.categories:
        assert f"Level {cat}:" in out


def test_a_fixture_paper_assembles_a_stage_c_prompt():
    paper = next(iter(seed_demo.load()["papers"].values()))
    prompt = build_evidence_prompt(_criteria()[0], paper["text"])
    assert "<text>" in prompt and paper["text"][:40] in prompt
    assert prompt.count("CRITERION: ") == 1


def test_the_papers_are_long_enough_to_be_attempts():
    for key, paper in seed_demo.load()["papers"].items():
        assert len(paper["text"]) > 200, f"{key} would be a strange thing to demonstrate with"
