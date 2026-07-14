"""Unit tests for app.marts.attendance_slice — the Phase 0 relevance stopgap.

`attendance_slice` is a pure function over a plan-extraction `document` dict (no DB), so these
run without a database. Run from backend/ (so `app` is importable):

    python -m pytest tests/test_marts.py -v

They pin the action-level attribution: a bundled multi-metric goal (belonging + suspension + a
real attendance target sharing one set of strategies) must NOT miscount its shared PD as an
attendance response, while its real attendance target is still surfaced. This is the Wilson HS
case. Durable fix (structured tags at extraction): docs/design/plan-relevance-tagging.md.
"""
from app.marts import attendance_slice


def _link(raw: str, metric_id: str | None = None) -> dict:
    return {"raw_metric_text": raw, "proposed_metric_id": metric_id}


def _action(text: str, links: list | None = None, budget: float | None = None) -> dict:
    return {
        "strategy_text": text,
        "metric_links": links or [],
        "action_number": None,
        "budgeted_amount": budget,
        "funding_source_raw": None,
    }


def _goal(statement: str, links: list | None = None, actions: list | None = None) -> dict:
    return {"statement": statement, "metric_links": links or [], "actions": actions or []}


def test_bundled_goal_does_not_sweep_shared_actions():
    """Wilson HS: a Culture/Climate goal bundles belonging + suspension + a real attendance
    target, served by shared PD. The PD must not be counted as an attendance response, and the
    92.2% attendance target must still surface."""
    climate = _goal(
        "Culture/Climate Goal: increase positive PULSE Sense of Belonging",
        links=[
            _link("Increase Sense of Belonging by 5%"),                       # belonging, no metric
            _link("Decrease Black Student Suspension by 3%", "suspension_rate"),
            _link("Increase Attendance rate by 3% (to 92.2%) by June 2026"),  # the real target
        ],
        actions=[
            _action("Courageous Conversations PD"),
            _action("Racial affinity clubs"),
            _action("Gholdy Muhammad look-fors"),
        ],
    )
    out = attendance_slice({"goals": [climate]})
    assert len(out) == 1                       # the goal still appears
    assert out[0]["actions"] == []             # shared climate PD is NOT swept in
    raws = [m["raw_metric_text"] for m in out[0]["metric_links"]]
    assert raws == ["Increase Attendance rate by 3% (to 92.2%) by June 2026"]  # target preserved


def test_dedicated_attendance_goal_sweeps_its_actions():
    """A single-topic attendance goal still attributes all its strategies, even when the action
    text itself doesn't repeat an attendance keyword (guards against a recall regression)."""
    goal = _goal(
        "Improve attendance and reduce chronic absenteeism",
        links=[_link("chronic absenteeism rate", "chronic_absenteeism_rate")],
        actions=[_action("Home visit re-engagement program"), _action("Daily SIS monitoring")],
    )
    out = attendance_slice({"goals": [goal]})
    assert len(out) == 1
    assert len(out[0]["actions"]) == 2         # both swept — no recall loss


def test_attendance_action_under_nonattendance_goal_is_kept():
    """An action that is itself about attendance is included even when its parent goal is not
    an attendance goal (the shared office aide filed under an Achievement measure)."""
    goal = _goal(
        "Increase Student Achievement",
        links=[_link("ELA proficiency", "ela_proficiency")],
        actions=[
            _action("Bilingual Office Aide for attendance and parent conferences", budget=49888),
            _action("Instructional coaching"),
        ],
    )
    out = attendance_slice({"goals": [goal]})
    assert len(out) == 1
    assert [a["strategy_text"] for a in out[0]["actions"]] == [
        "Bilingual Office Aide for attendance and parent conferences"
    ]


def test_unrelated_goal_is_omitted():
    """A goal with no attendance relevance at goal or action level drops out entirely."""
    goal = _goal(
        "Increase Student Achievement",
        links=[_link("ELA proficiency", "ela_proficiency")],
        actions=[_action("Instructional coaching")],
    )
    assert attendance_slice({"goals": [goal]}) == []
