"""summarize_traces — the pure aggregation behind the admin eval dashboard (no DB).

Pins the shape the UI reads and the tolerance the trace store needs: half-populated rows
(missing totals, null latency, unknown status) must never throw, and identity is never in
the output.
"""
import datetime as _dt

from app.evals_view import (
    _shape_event, shape_case, shape_result, shape_run, shape_trace_detail, summarize_traces,
)

_TS = _dt.datetime(2026, 7, 21, tzinfo=_dt.timezone.utc)


def _r(status="ok", source="prod", latency=1000, model="claude-haiku-4-5",
       cost=0.02, inp=10000, out=200, **extra):
    return {
        "status": status, "source": source, "latency_ms": latency, "model": model,
        "totals": {"cost_usd_est": cost, "input_tokens": inp, "output_tokens": out},
        **extra,
    }


def test_empty_summary_is_all_zeros_not_a_crash():
    s = summarize_traces([])
    assert s["traces"] == 0
    assert s["ok_rate"] is None
    assert s["cost_usd"] == 0
    assert s["latency_p50_ms"] is None


def test_aggregates_counts_cost_tokens_and_status():
    rows = [_r(status="ok"), _r(status="ok"), _r(status="error", cost=0.05)]
    s = summarize_traces(rows)
    assert s["traces"] == 3
    assert s["by_status"] == {"ok": 2, "error": 1}
    assert s["ok_rate"] == round(100 * 2 / 3, 1)
    assert s["cost_usd"] == round(0.02 + 0.02 + 0.05, 4)
    assert s["tokens"] == 3 * (10000 + 200)
    assert s["by_model"] == {"claude-haiku-4-5": 3}


def test_latency_percentiles_ignore_nulls():
    rows = [_r(latency=100), _r(latency=None), _r(latency=900)]
    s = summarize_traces(rows)
    # only the two non-null latencies count
    assert s["latency_max_ms"] == 900
    assert s["latency_p50_ms"] in (100, 900)  # midpoint of a 2-element sorted list


def test_tolerates_missing_totals_and_unknown_status():
    rows = [{"status": None, "source": None, "latency_ms": None, "model": None, "totals": None}]
    s = summarize_traces(rows)  # must not raise
    assert s["traces"] == 1
    assert s["by_status"] == {"unknown": 1}
    assert s["by_source"] == {"prod": 1}
    assert s["cost_usd"] == 0


def test_source_split_separates_prod_from_eval():
    rows = [_r(source="prod"), _r(source="eval"), _r(source="eval")]
    assert summarize_traces(rows)["by_source"] == {"prod": 1, "eval": 2}


# --- row shapers for the cases / runs / results tabs -------------------------------------- #


def test_shape_case_pulls_level_and_graders():
    c = shape_case({"eval_case_id": "seed-1", "question": "q", "ui": {"level": "High"},
                    "expected": {"graders": ["numeric_provenance"], "params": {}},
                    "source": "seed", "status": "active", "tags": ["honesty"], "created_at": _TS})
    assert c["level"] == "High" and c["graders"] == ["numeric_provenance"]
    assert c["tags"] == ["honesty"] and c["created_at"].startswith("2026-07-21")


def test_shape_case_tolerates_missing_ui_and_expected():
    c = shape_case({"eval_case_id": "x", "question": "q", "status": "candidate",
                    "source": "mined:t"})
    assert c["level"] is None and c["graders"] == [] and c["tags"] == []


def test_shape_run_flattens_aggregates():
    s = shape_run({"eval_run_id": "run1", "ts": _TS, "set_name": "golden", "target": "live",
                   "model": "claude-haiku-4-5", "cost_usd": 0.4, "baseline_run_id": None,
                   "aggregates": {"n": 10, "passed": 8, "failed": 2, "error": 0, "pass_rate": 0.8}})
    assert (s["pass_rate"], s["n"], s["passed"], s["cost_usd"]) == (0.8, 10, 8, 0.4)
    assert s["ts"].startswith("2026-07-21")


def test_shape_result_keeps_verdict_scores_and_trace():
    s = shape_result({"eval_case_id": "c1", "question": "q", "verdict": "fail",
                      "scores": {"numeric_provenance": {"verdict": "fail"}},
                      "judge_rationale": None, "trace_id": "t1"})
    assert s["verdict"] == "fail" and s["trace_id"] == "t1"
    assert "numeric_provenance" in s["scores"]


# --- trace detail (envelope + event stream) ----------------------------------------------- #


def test_shape_event_trims_each_type_to_its_useful_fields():
    assert _shape_event({"type": "turn_start", "question": "q?", "span_id": "x"}) == {
        "type": "turn_start", "question": "q?", "prior_messages": None}
    tc = _shape_event({"type": "tool_call", "name": "compare_to_peers", "input": {"a": 1},
                       "output": {"v": 2}, "error": None, "latency_ms": 5, "span_id": "x"})
    assert tc["name"] == "compare_to_peers" and tc["output"] == {"v": 2} and "span_id" not in tc
    assert _shape_event({"type": "turn_end", "reply": "hi"})["reply"] == "hi"


def test_shape_trace_detail_pulls_level_and_shapes_events():
    row = {"trace_id": "t1", "session_id": "s", "ts": _TS, "status": "ok", "source": "prod",
           "model": "claude-haiku-4-5", "question": "q?", "ui": {"level": "High"},
           "versions": {"git_sha": "abc"}, "totals": {"cost_usd_est": 0.01}, "gcs_uri": "gs://x"}
    events = [{"type": "turn_start", "question": "q?"},
              {"type": "tool_call", "name": "t", "input": {}, "output": {}, "error": None},
              {"type": "turn_end", "reply": "answer"}]
    d = shape_trace_detail(row, events)
    assert d["level"] == "High" and d["ts"].startswith("2026-07-21")
    assert [e["type"] for e in d["events"]] == ["turn_start", "tool_call", "turn_end"]
    assert d["events"][2]["reply"] == "answer"
