"""Unit tests for app.marts.attendance_slice — the Phase 0 relevance stopgap.

`attendance_slice` is a pure function over a plan-extraction `document` dict (no DB), so these
run without a database. Run from backend/ (so `app` is importable):

    python -m pytest tests/test_marts.py -v

They pin the action-level attribution: a bundled multi-metric goal (belonging + suspension + a
real attendance target sharing one set of strategies) must NOT miscount its shared PD as an
attendance response, while its real attendance target is still surfaced. This is the Wilson HS
case. Durable fix (structured tags at extraction): docs/design/plan-relevance-tagging.md.
"""
from app.marts import (
    SlotSpec,
    SpotlightItem,
    attendance_slice,
    band_status,
    full_plan_goals,
    resolve_spotlight,
    subgroup_slice,
    validate_slot_spec,
)


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


# --------------------------------------------------------------------------- #
# subgroup_slice — the pure shaping half of fetch_metric_by_subgroup (no DB).
# --------------------------------------------------------------------------- #
def _grow(gid: str, dim: str, value, status="reported", n=100) -> dict:
    return {"student_group_id": gid, "label": gid, "dimension": dim,
            "value": value, "value_status": status, "n_size": n}


def test_subgroup_slice_computes_gap_vs_all():
    """Each subgroup gets a raw (value − All Students) gap; All Students itself gets none."""
    rows = [_grow("all", "total", 20.0), _grow("race_black", "race", 32.0), _grow("race_white", "race", 12.5)]
    out = subgroup_slice(rows)
    assert out["all_students_value"] == 20.0
    assert out["subgroup_count"] == 3
    by_id = {s["student_group_id"]: s for s in out["subgroups"]}
    assert by_id["all"]["gap_vs_all"] is None            # All Students isn't compared to itself
    assert by_id["race_black"]["gap_vs_all"] == 12.0     # worse (lower_better metric): positive gap
    assert by_id["race_white"]["gap_vs_all"] == -7.5


def test_subgroup_slice_suppressed_value_stays_unknown():
    """A suppressed subgroup keeps value=None and gets NO gap — never coerced to 0."""
    rows = [_grow("all", "total", 20.0), _grow("foster", "program", None, status="suppressed", n=None)]
    out = subgroup_slice(rows)
    foster = next(s for s in out["subgroups"] if s["student_group_id"] == "foster")
    assert foster["value"] is None
    assert foster["value_status"] == "suppressed"
    assert foster["gap_vs_all"] is None                  # no false "0% → same as everyone" claim


def test_subgroup_slice_missing_all_row_yields_no_gaps():
    """If the All Students value is absent, gaps are undefined (None), not computed off a subgroup."""
    rows = [_grow("all", "total", None, status="suppressed"), _grow("race_hispanic", "race", 25.0)]
    out = subgroup_slice(rows)
    assert out["all_students_value"] is None
    hisp = next(s for s in out["subgroups"] if s["student_group_id"] == "race_hispanic")
    assert hisp["value"] == 25.0
    assert hisp["gap_vs_all"] is None


# --------------------------------------------------------------------------- #
# Workspace slot validation — the spec gate for the Claude-controlled charts
# (docs/design/agentic-workspace-and-sessions.md). Pure: the reference sets are
# passed in, so no DB. The invariant under test: an INVALID spec is a correctable
# error (the message lists valid values so the model fixes its call); MISSING data
# behind a valid spec is never an error — missingness is honest payload content.
# --------------------------------------------------------------------------- #
META = {
    "chronic_absenteeism_rate": {"metric_id": "chronic_absenteeism_rate",
                                 "display_name": "Chronic Absenteeism Rate",
                                 "direction": "lower_better", "applies_to_levels": "ES,MS,HS"},
    "grad_rate_acgr": {"metric_id": "grad_rate_acgr", "display_name": "Graduation Rate (ACGR)",
                       "direction": "higher_better", "applies_to_levels": "HS"},
}
YEARS = {"2022-23", "2023-24"}
GROUPS = {"all", "el", "swd", "sed"}


def _spec(m="chronic_absenteeism_rate", y=None, g="all") -> SlotSpec:
    return SlotSpec(metric_id=m, school_year=y, student_group_id=g)


def _validate(spec, level="High"):
    return validate_slot_spec(spec, META, level, YEARS, GROUPS)


def test_valid_default_spec_passes():
    assert _validate(_spec()) is None


def test_unknown_metric_error_lists_the_whitelist():
    """The error is corrective: it names every chartable metric so the model can fix the call."""
    err = _validate(_spec(m="enrollment"))
    assert "not a chartable metric" in err
    assert "chronic_absenteeism_rate" in err and "grad_rate_acgr" in err


def test_hs_only_metric_is_rejected_for_a_middle_school():
    """grad_rate_acgr for a Middle school → an explicit corrective error, not an empty chart."""
    err = _validate(_spec(m="grad_rate_acgr"), level="Middle")
    assert "not reported for Middle schools" in err
    assert "HS" in err
    assert _validate(_spec(m="grad_rate_acgr"), level="High") is None


def test_unknown_year_format_is_corrected():
    """'2023' (vs '2023-24') is a spec mistake — corrected, with the known years listed."""
    err = _validate(_spec(y="2023"))
    assert "unknown school_year '2023'" in err
    assert "2023-24" in err


def test_valid_year_is_never_checked_for_data():
    """A known year passes even if this school has no rows there — the validator gates the
    VOCABULARY only. Whether data exists is the payload's business (`value_status`), because
    'no data for 2022-23' is a finding to show, not a call to reject."""
    assert _validate(_spec(y="2022-23")) is None


def test_unknown_subgroup_is_rejected_with_the_known_groups():
    err = _validate(_spec(g="race_martian"))
    assert "unknown student_group_id 'race_martian'" in err
    assert "el" in err and "swd" in err


def test_band_status_flags_thin_bands_only():
    """A subgroup band shrinks when peers' values are privacy-suppressed. Below the floor the
    band is CAPTIONED, never hidden — honesty over tidiness."""
    assert "thin band: only 4" in band_status(4)
    assert band_status(10) is None
    assert band_status(None) is None  # no distribution at all — nothing to caption


# --------------------------------------------------------------------------- #
# Spotlight resolution — Claude pins plan items BY REFERENCE; everything rendered
# comes from the stored plan rows. The model's only authored text is `reason`.
# --------------------------------------------------------------------------- #
def _served_plan(*goals, plan_year="2024-25") -> dict:
    return {"has_plan": True, "plan_status": "on_file", "plan_year": plan_year,
            "goals": full_plan_goals({"goals": list(goals)})}


def _raw_goal(statement="Improve attendance", n_actions=2) -> dict:
    return {"goal_number": 1, "statement": statement,
            "actions": [{"strategy_text": f"strategy {i}", "budgeted_amount": 1000.0 * i}
                        for i in range(n_actions)]}


def test_spotlight_whole_goal_pin_carries_all_its_actions():
    plan = _served_plan(_raw_goal())
    out = resolve_spotlight([SpotlightItem(goal_index=0, reason="relevant")], plan)
    assert out["plan_year"] == "2024-25"
    assert [a["strategy_text"] for a in out["items"][0]["actions"]] == ["strategy 0", "strategy 1"]
    assert out["items"][0]["statement"] == "Improve attendance"  # from the plan, not the model


def test_spotlight_action_indices_select_and_out_of_range_actions_drop():
    plan = _served_plan(_raw_goal(n_actions=3))
    out = resolve_spotlight(
        [SpotlightItem(goal_index=0, action_indices=[2, 9], reason="r")], plan)
    assert [a["action_index"] for a in out["items"][0]["actions"]] == [2]


def test_spotlight_out_of_range_goal_is_dropped_with_a_corrective_note():
    """A bad ref is dropped and NAMED — never guessed to a nearby goal."""
    plan = _served_plan(_raw_goal())
    out = resolve_spotlight([SpotlightItem(goal_index=0, reason="ok"),
                             SpotlightItem(goal_index=7, reason="bad")], plan)
    assert len(out["items"]) == 1
    assert "out-of-range goal_index refs [7]" in out["note"]
    assert "0-based" in out["note"]


def test_spotlight_reason_is_truncated():
    """`reason` is the ONE model-authored line that renders — capped, a caption not an essay."""
    plan = _served_plan(_raw_goal())
    out = resolve_spotlight([SpotlightItem(goal_index=0, reason="x" * 500)], plan)
    assert len(out["items"][0]["reason"]) == 200


def test_full_plan_goals_emits_canonical_index_paths():
    """goal_index/action_index are the spotlight reference format — positions in this served
    array, because goal_number/action_number come from extraction and can be null."""
    goals = full_plan_goals({"goals": [
        {"goal_number": None, "actions": [{"strategy_text": "a"}, {"strategy_text": "b"}]},
        {"goal_number": "2", "actions": []},
    ]})
    assert [g["goal_index"] for g in goals] == [0, 1]
    assert [a["action_index"] for a in goals[0]["actions"]] == [0, 1]
