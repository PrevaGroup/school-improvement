"""The one-command loop, and the two things it must not quietly become.

A convenience wrapper around a gated pipeline is exactly where the gate goes to die: the wrapper
knows the answer, the wrapper is what everyone runs, and one day the wrapper stops asking. These
tests are about that, not about whether the stages work — each stage has its own tests.
"""
from __future__ import annotations

import inspect

import pytest

from scripts import demo_loop


def test_the_loop_confirms_through_the_gate_rather_than_around_it():
    """It calls `intake.gate.confirm` — the same statement the API endpoint uses. A wrapper that
    wrote its own UPDATE would be a second implementation of the gate, and a gate implemented
    twice can be opened two ways and closed one."""
    src = inspect.getsource(demo_loop.run)
    assert "from intake.gate import confirm" in src
    assert "UPDATE intake_manifest" not in src, "the loop is writing its own confirmation"
    assert "confirmed_at" not in src, "the loop is touching the gate column directly"


def test_a_confirmation_still_needs_a_name():
    """`--as` is required for the same reason the CHECK in 0024 is. The loop performs the
    confirmation AS somebody rather than around them, and the moment that feels like a formality
    is the moment the gate has stopped working."""
    src = inspect.getsource(demo_loop.main)
    assert "--as is required" in src
    assert 'ap.error("--as is required' in src or "ap.error(" in src


def test_the_confirming_name_reaches_the_database():
    """Not a placeholder, not the script's own name — the person who ran it."""
    src = inspect.getsource(demo_loop.run)
    assert "confirm(conn, state[\"manifest_id\"], who, tenant)" in src


def test_reading_and_confirming_stay_separate_stages():
    """If they merged, one invocation would both propose a set and agree with it, which is the
    thing the gate exists to prevent."""
    assert demo_loop.STAGES.index("read") < demo_loop.STAGES.index("confirm")
    assert "read" in demo_loop.STAGES and "confirm" in demo_loop.STAGES


# ------------------------------------------------------------------ cost and teardown


def test_only_scoring_and_composing_cost_money():
    """`--stop-at bind` has to be genuinely free, or the cheap loop is not cheap and nobody uses
    it. Every earlier stage is database work."""
    assert demo_loop.COSTS_MONEY == ("score", "compose")
    for free in ("seed", "read", "confirm", "bind"):
        assert free not in demo_loop.COSTS_MONEY


def test_stopping_early_is_a_prefix_of_the_full_run():
    """`--stop-at` slices the stage list, so a stopped run is the same run, shorter. A separate
    code path for the cheap loop would drift from the real one and stop testing it."""
    src = inspect.getsource(demo_loop.run)
    assert "STAGES[: STAGES.index(stop_at) + 1]" in src


@pytest.mark.parametrize("stage", demo_loop.STAGES)
def test_every_stage_has_a_runner(stage):
    """A stage named in the list and missing from the dispatch would raise KeyError halfway
    through a loop somebody was mid-way through trusting."""
    src = inspect.getsource(demo_loop.run)
    assert f'"{stage}":' in src


def test_teardown_removes_children_before_parents():
    """A purge running the other way round trips a foreign key halfway and leaves the database
    neither empty nor seeded — the worst of both for somebody trying to iterate."""
    src = inspect.getsource(demo_loop.reset)
    assert src.index("scoring_seed.purge()") < src.index("registry_seed.purge()")
    assert src.index("registry_seed.purge()") < src.index("roster_seed.purge()")


def test_teardown_removes_the_manifests_too():
    """Intake rows outlive an artifact purge. A stale unconfirmed read left behind sits in the
    Folders list forever looking like work somebody has to do."""
    src = inspect.getsource(demo_loop.reset)
    assert "DELETE FROM intake_file" in src
    assert "DELETE FROM intake_manifest" in src


def test_a_failing_stage_stops_the_loop():
    """Continuing past a failure would score papers bound from a folder that never read cleanly,
    and the summary would show a green run with one red line in the middle of it."""
    src = inspect.getsource(demo_loop.run)
    assert 'if not step["ok"]:' in src and "break" in src


def test_the_summary_says_whether_anything_spent_money():
    """So a run you thought was free and was not is visible at the bottom of the output rather
    than at the end of the month."""
    src = inspect.getsource(demo_loop.main)
    assert "stages_that_cost_money" in src
