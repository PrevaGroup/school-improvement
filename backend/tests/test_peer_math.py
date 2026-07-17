"""Characterization tests for the pure helpers in app/marts.py that are about to change module.

`_pctile` belongs to likeschools (it shapes the peer distribution in `fetch_peer_benchmark`);
`full_plan_goals` belongs to plan_marts. Both currently sit in the same file, and the reorg
(docs/MODULES.md) splits that file along the module line. These pin today's behavior so the
move is provably behavior-preserving — the values here were read off the current code, not
derived from what it ought to do.

The `fetch_*` functions around them are raw-SQL/DB-bound and stay uncovered here; the HTTP
surface they serve is pinned separately in tests/test_route_contract.py.
"""
from app.marts import _pctile, full_plan_goals


# --------------------------------------------------------------------------- #
# _pctile — linear interpolation between neighbours (likeschools)
# --------------------------------------------------------------------------- #
def test_pctile_empty_is_none():
    assert _pctile([], 50) is None


def test_pctile_single_value_ignores_the_quantile():
    # n=1 short-circuits: a lone school's band has no spread to interpolate across.
    assert _pctile([7.0], 50) == 7.0
    assert _pctile([7.0], 0) == 7.0
    assert _pctile([7.0], 100) == 7.0


def test_pctile_endpoints_are_min_and_max():
    vals = [1.0, 2.0, 3.0, 4.0]
    assert _pctile(vals, 0) == 1.0
    assert _pctile(vals, 100) == 4.0


def test_pctile_interpolates_between_neighbours():
    # p50 of 4 values falls between the 2nd and 3rd -> 2.5, not a member of the input.
    assert _pctile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert _pctile([1.0, 2.0, 3.0, 4.0], 25) == 1.75


# --------------------------------------------------------------------------- #
# full_plan_goals — the UNfiltered plan view (plan_marts)
# --------------------------------------------------------------------------- #
def test_full_plan_goals_empty_document():
    assert full_plan_goals({}) == []
    assert full_plan_goals({"goals": None}) == []


def test_full_plan_goals_keeps_a_goal_with_no_actions():
    out = full_plan_goals({"goals": [{"goal_number": 1, "statement": "S"}]})
    assert out == [{
        "goal_index": 0,  # canonical spotlight ref — positions, since goal_number can be null
        "goal_number": 1, "goal_type": None, "statement": "S",
        "provenance": None, "actions": [],
    }]


def test_full_plan_goals_keeps_every_topic():
    """The point of this function vs. attendance_slice: NO relevance filtering.

    attendance_slice drops non-attendance goals; this one must not, or the chat's
    full-plan tool silently loses the ELA/math/climate goals it exists to answer about.
    """
    doc = {"goals": [
        {"goal_number": 1, "statement": "Raise ELA proficiency", "actions": []},
        {"goal_number": 2, "statement": "Reduce chronic absenteeism", "actions": []},
        {"goal_number": 3, "statement": "Improve school climate", "actions": []},
    ]}
    assert [g["goal_number"] for g in full_plan_goals(doc)] == [1, 2, 3]


def test_full_plan_goals_carries_action_budget_and_provenance():
    doc = {"goals": [{
        "goal_number": 1, "goal_type": "academic", "statement": "S", "provenance": {"page": 3},
        "actions": [{
            "action_number": "1.1", "strategy_text": "Tutoring",
            "budgeted_amount": 5000.0, "funding_source_raw": "LCFF",
            "provenance": {"page": 4},
        }],
    }]}
    action = full_plan_goals(doc)[0]["actions"][0]
    assert action["budgeted_amount"] == 5000.0
    assert action["funding_source_raw"] == "LCFF"
    assert action["provenance"] == {"page": 4}
