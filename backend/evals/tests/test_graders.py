"""Grader unit tests — pure, no DB, no network (the judge takes an injected callable).

Each grader is exercised on all three verdicts where it has them (pass / fail / na), because
`na` (the case didn't exercise this rule) is load-bearing: it must not count as a failure.
"""
from __future__ import annotations

from evals.graders import (
    Bundle, bundle_from_lines, efficiency, expected_tools, no_redundant_tool_calls,
    numeric_provenance, plan_status_compliance, resolution_correctness, run_graders,
    suppressed_value_handling, usefulness_judge,
)


def _b(reply="", tool_calls=None, status="ok", totals=None, ui=None, question="q", latency_ms=None):
    tool_calls = tool_calls or []
    env = {"status": status, "totals": totals or {}, "ui": ui or {}, "latency_ms": latency_ms}
    return Bundle(
        envelope=env, events=[], reply=reply, status=status,
        tools_used=sorted({tc["name"] for tc in tool_calls if tc.get("name")}),
        tool_calls=tool_calls, totals=totals or {}, ui=ui or {}, question=question)


# --------------------------------------------------------------------------- bundle parsing


def test_bundle_from_lines_hoists_reply_question_and_tool_outputs():
    lines = [
        {"trace_id": "t1", "status": "ok", "totals": {"iterations": 2}, "ui": {"level": "High"}},
        {"type": "turn_start", "question": "how is Wilson?"},
        {"type": "tool_call", "name": "compare_to_peers", "input": {"x": 1},
         "output": {"target_value": 0.23}, "error": None},
        {"type": "turn_end", "reply": "Wilson's rate is 23%."},
    ]
    b = bundle_from_lines(lines)
    assert b.reply == "Wilson's rate is 23%." and b.question == "how is Wilson?"
    assert b.tools_used == ["compare_to_peers"]
    assert b.tool_calls[0]["output"] == {"target_value": 0.23}
    assert b.totals == {"iterations": 2}


# --------------------------------------------------------------------------- T1


def test_numeric_provenance_grounds_percentages_against_fractions():
    b = _b(reply="Chronic absenteeism is 23.4%.",
           tool_calls=[{"name": "compare_to_peers", "output": {"target_value": 0.234}}])
    assert numeric_provenance(b, {}).verdict == "pass"


def test_numeric_provenance_flags_invented_figures():
    b = _b(reply="The plan budgets $1,250,000 for attendance.", tool_calls=[])
    r = numeric_provenance(b, {})
    assert r.verdict == "fail" and "1250000" in r.detail


def test_numeric_provenance_ignores_years_and_small_counts():
    b = _b(reply="In 2023 the plan set 3 goals.", tool_calls=[])
    assert numeric_provenance(b, {}).verdict == "na"


def test_numeric_provenance_grounds_a_rounded_percentage():
    b = _b(reply="About 75% are socioeconomically disadvantaged.",
           tool_calls=[{"name": "x", "output": {"pct_sed": 75.8}}])
    assert numeric_provenance(b, {}).verdict == "pass"          # 75 vs 75.8 is a rounding


def test_numeric_provenance_grounds_an_abbreviated_dollar_amount():
    b = _b(reply="The plan funds a counselor at $187.8K.",
           tool_calls=[{"name": "x", "output": {"budgeted_amount": 187176}}])
    assert numeric_provenance(b, {}).verdict == "pass"          # 187.8K -> 187800 ~ 187176


def test_numeric_provenance_grounds_sums_of_budgets():
    tc = [{"name": "x", "output": {"actions": [
        {"budgeted_amount": 187176}, {"budgeted_amount": 99774},
        {"budgeted_amount": 16242}, {"budgeted_amount": 16242}]}}]
    # $32,484 = the two aides; $319,434 = the grand total — both derived, both grounded now.
    b = _b(reply="Two aides total $32,484; all funded actions come to $319,434.", tool_calls=tc)
    assert numeric_provenance(b, {}).verdict == "pass"


def test_numeric_provenance_detail_names_the_nearest_value():
    b = _b(reply="The plan budgets $250,000 for this.",
           tool_calls=[{"name": "x", "output": {"budgeted_amount": 187176}}])
    r = numeric_provenance(b, {})
    assert r.verdict == "fail"
    assert "250000" in r.detail and "nearest tool value 187176" in r.detail
    # evidence carries the bare numbers so the UI can highlight them in the answer + tool output.
    assert r.evidence == {"reply": ["250000"], "tool": ["187176"]}


def test_plan_status_compliance_catches_the_defamation_pattern():
    tc = [{"name": "query_school_plan", "output": {"plan_status": "not_on_file"}}]
    assert plan_status_compliance(_b(reply="Jordan has no plan.", tool_calls=tc), {}).verdict == "fail"
    # the honest phrasing passes...
    assert plan_status_compliance(
        _b(reply="Jordan's plan is not on file.", tool_calls=tc), {}).verdict == "pass"
    # "has no plan on file" is qualified -> also fine
    assert plan_status_compliance(
        _b(reply="Jordan has no plan on file.", tool_calls=tc), {}).verdict == "pass"
    # ...and with no not_on_file signal the grader abstains
    assert plan_status_compliance(_b(reply="Jordan has no plan.", tool_calls=[]), {}).verdict == "na"


def test_suppressed_value_must_not_read_as_zero():
    tc = [{"name": "query_subgroup_metrics", "output": {"value_status": "suppressed"}}]
    assert suppressed_value_handling(_b(reply="The rate is 0%.", tool_calls=tc), {}).verdict == "fail"
    assert suppressed_value_handling(
        _b(reply="That value is suppressed for privacy.", tool_calls=tc), {}).verdict == "pass"
    assert suppressed_value_handling(_b(reply="The rate is 0%.", tool_calls=[]), {}).verdict == "na"


def test_resolution_correctness_checks_the_school_id():
    tc = [{"name": "set_school", "input": {}, "output": {"school_id": "S1"}}]
    assert resolution_correctness(_b(tool_calls=tc), {"school_id": "S1"}).verdict == "pass"
    assert resolution_correctness(_b(tool_calls=tc), {"school_id": "S2"}).verdict == "fail"
    assert resolution_correctness(_b(tool_calls=tc), {}).verdict == "na"


# --------------------------------------------------------------------------- T3


def test_expected_tools():
    b = _b(tool_calls=[{"name": "compare_to_peers"}])
    assert expected_tools(b, {"tools": ["compare_to_peers"]}).verdict == "pass"
    assert expected_tools(b, {"tools": ["query_school_plan"]}).verdict == "fail"
    assert expected_tools(b, {}).verdict == "na"


def test_no_redundant_tool_calls():
    same = [{"name": "compare_to_peers", "input": {"school_name": "Wilson"}},
            {"name": "compare_to_peers", "input": {"school_name": "Wilson"}}]
    assert no_redundant_tool_calls(_b(tool_calls=same), {}).verdict == "fail"
    diff = [{"name": "compare_to_peers", "input": {"school_name": "Wilson"}},
            {"name": "compare_to_peers", "input": {"school_name": "Poly"}}]
    assert no_redundant_tool_calls(_b(tool_calls=diff), {}).verdict == "pass"


def test_efficiency_budget():
    assert efficiency(_b(totals={"iterations": 6}), {"max_iterations": 4}).verdict == "fail"
    assert efficiency(_b(totals={"iterations": 2}), {"max_iterations": 4}).verdict == "pass"
    assert efficiency(_b(totals={"iterations": 6}), {}).verdict == "na"


# --------------------------------------------------------------------------- T2 judge


def test_usefulness_judge_is_na_without_a_judge():
    assert usefulness_judge(_b(reply="hi"), {}, judge=None).verdict == "na"


def test_usefulness_judge_parses_score_and_verdict():
    good = lambda p: '{"score": 0.9, "verdict": "pass", "rationale": "grounded and actionable"}'
    r = usefulness_judge(_b(reply="do X then Y"), {}, judge=good)
    assert r.verdict == "pass" and r.score == 0.9 and "actionable" in r.detail

    weak = lambda p: 'prefix {"score": 0.3, "rationale": "just restates the screen"} suffix'
    assert usefulness_judge(_b(reply="the number is on screen"), {}, judge=weak).verdict == "fail"


def test_usefulness_judge_swallows_a_broken_judge_response():
    assert usefulness_judge(_b(reply="x"), {}, judge=lambda p: "not json").verdict == "na"


# --------------------------------------------------------------------------- orchestration


def test_run_graders_fails_overall_on_a_gating_failure():
    b = _b(reply="Budget is $999,999.", tool_calls=[])   # ungrounded number -> T1 fail
    out = run_graders(b, {"graders": ["numeric_provenance"]})
    assert out["verdict"] == "fail"
    assert out["scores"]["numeric_provenance"]["verdict"] == "fail"


def test_run_graders_surfaces_an_unknown_grader_instead_of_skipping_it():
    out = run_graders(_b(reply="x"), {"graders": ["not_a_grader", "numeric_provenance"]})
    assert out["scores"]["not_a_grader"]["verdict"] == "na"
    assert "unknown grader" in out["scores"]["not_a_grader"]["detail"]


def test_run_graders_passes_when_all_pass_and_reports_error_status():
    b = _b(reply="Wilson's rate is 23%.",
           tool_calls=[{"name": "compare_to_peers", "output": {"target_value": 0.23}}])
    assert run_graders(b, {"graders": ["numeric_provenance", "expected_tools"],
                           "params": {"tools": ["compare_to_peers"]}})["verdict"] == "pass"
    assert run_graders(_b(status="error"), {"graders": ["numeric_provenance"]})["verdict"] == "error"


# --------------------------------------------------------------- normalized shape + versioning (P1)


def test_every_scored_grader_carries_a_version():
    """P1: run_graders stamps a grader_version onto every result — a score is attributable."""
    out = run_graders(_b(reply="x"), {"graders": ["numeric_provenance", "usefulness_judge"]},
                      judge=None)
    assert out["scores"]["numeric_provenance"]["version"] == "v1"
    # the judge tracks its own rubric version, surfaced per-result too
    from evals.graders import JUDGE_RUBRIC_VERSION
    assert out["scores"]["usefulness_judge"]["version"] == JUDGE_RUBRIC_VERSION


# ------------------------------------------------------------------- third-party graders (P2)


def _fake_lc_client(payload):
    """Stand-in for a third-party evaluator returning the neutral {score,label,explanation}
    envelope (the shape LC's SDK returns) — proves the adapter without any live call."""
    return {"score": 0.82, "label": "grade-4", "explanation": "reads at target band"}


def test_external_grader_is_na_without_a_client():
    from evals.graders import EXTERNAL_GRADERS
    r = EXTERNAL_GRADERS["external_content_quality"].run(_b(reply="hi"), {}, client=None)
    assert r.verdict == "na" and "no external grader client" in r.detail


def test_external_grader_normalizes_a_third_party_envelope():
    from evals.graders import EXTERNAL_GRADERS
    r = EXTERNAL_GRADERS["external_content_quality"].run(
        _b(reply="a passage"), {"external_threshold": 0.6}, client=_fake_lc_client)
    assert r.verdict == "pass" and r.score == 0.82
    assert r.evidence == {"label": "grade-4"} and "target band" in r.detail


def test_run_graders_dispatches_external_grader_with_injected_client():
    out = run_graders(_b(reply="a passage"), {"graders": ["external_content_quality"]},
                      clients={"external_content_quality": _fake_lc_client})
    assert out["scores"]["external_content_quality"]["verdict"] == "pass"
    assert out["scores"]["external_content_quality"]["version"] == "v1"


def test_external_grader_does_not_gate_the_overall_verdict_by_default():
    """A failing third-party grader is advisory (gating=False) — it must not flip a PR red."""
    low = lambda payload: {"score": 0.1, "label": "grade-8", "explanation": "too complex"}
    out = run_graders(_b(reply="a passage"), {"graders": ["external_content_quality"]},
                      clients={"external_content_quality": low})
    assert out["scores"]["external_content_quality"]["verdict"] == "fail"
    assert out["verdict"] == "pass"        # advisory: does not gate
