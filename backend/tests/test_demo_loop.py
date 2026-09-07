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
    order = [src.index(f"{m}_seed.purge(") for m in ("scoring", "registry", "roster")]
    assert order == sorted(order), "artifacts must go before the registry, and both before roster"


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


def test_the_summary_reports_what_was_spent_not_which_stages_ran():
    """It listed `score` and `compose` whenever they executed — including a run where both found
    nothing to do and made zero calls, reporting a cost that had not happened.

    Counting the calls cannot make that mistake, and the estimate is the thing somebody actually
    wants at the bottom of a run they thought was free."""
    src = inspect.getsource(demo_loop.main)
    assert "model_calls" in src and "cost_usd_estimate" in src
    assert "stages_that_cost_money" not in src


def test_the_teardown_checks_what_is_left_rather_than_what_it_deleted():
    """Three teardown bugs in this session each deleted some rows, returned a number, and left
    the ones that mattered: a `demo-` prefix nothing carried any more, a table added after the
    delete list was written, and a run id the creation path had stopped using.

    A count of SURVIVORS cannot make that mistake, and it raises rather than reporting."""
    src = inspect.getsource(demo_loop.reset)
    assert "verify(" in src
    assert "still_there" in src
    assert "raise RuntimeError" in src


def test_the_teardown_covers_artifacts_bind_created():
    """`bind` stamps the MANIFEST id as an artifact's run, not the fixture's RUN_ID. Run-scoping
    alone left every bind-created artifact behind, and the next bind then skipped two of three
    files as unchanged with nothing to explain why."""
    src = inspect.getsource(demo_loop.reset)
    assert "include_intake_derived=True" in src


def test_the_teardown_verifies_every_table_it_deletes():
    """DERIVED, so the two lists cannot drift. `verify()` once counted three tables while the
    purge deleted four — and the delivery table it missed was the one the purge had just been
    taught about, so the check passed while the gap it exists to find was open.

    Worse, the edit that was supposed to add it was a silent no-op: a string replace that matched
    nothing, followed by a print saying it had worked. The assertion is the fix for that, and this
    test is the fix for it happening again.
    """
    from scoring.seed_demo import _PURGE_ORDER, verify

    counted = inspect.getsource(verify)
    missing = [t for t, _ in _PURGE_ORDER
               if t != "artifact_state_transition" and f'"{t}"' not in counted]
    assert not missing, (
        f"the purge deletes {missing} and the teardown check does not count them, so a scope "
        f"that misses them reports success.")
