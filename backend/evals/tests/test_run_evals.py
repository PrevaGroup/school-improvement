"""Runner tests: the pure `assemble` scoring core + the I/O wiring (seams patched)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import evals.run_evals as re
from evals.run_evals import assemble

_NOW = datetime(2026, 7, 21, tzinfo=timezone.utc)


def _trace(trace_id: str, reply: str, tool_calls=(), *, cost=0.01, model="claude-haiku-4-5") -> str:
    env = {"trace_id": trace_id, "status": "ok", "ui": {"level": "High"},
           "totals": {"cost_usd_est": cost, "iterations": 1}, "versions": {"git_sha": "abc123"},
           "gen_ai.provider.name": "anthropic", "gen_ai.request.model": model}
    events = [{"type": "turn_start", "question": "q"}]
    events += [{"type": "tool_call", **tc} for tc in tool_calls]
    events.append({"type": "turn_end", "reply": reply})
    return "\n".join(json.dumps(x) for x in [env, *events])


_GROUNDED = _trace("t1", "Wilson's rate is 23%.",
                   [{"name": "compare_to_peers", "input": {}, "output": {"target_value": 0.23},
                     "error": None}])
_INVENTED = _trace("t2", "The plan budgets $999,999.")


def _cases():
    return [
        {"eval_case_id": "c1", "question": "q", "ui": {"level": "High"},
         "expected": {"graders": ["numeric_provenance"]}, "tags": ["honesty"]},
        {"eval_case_id": "c2", "question": "q", "ui": {"level": "High"},
         "expected": {"graders": ["numeric_provenance"]}, "tags": ["honesty"]},
        {"eval_case_id": "c3", "question": "q", "ui": {}, "expected": {}, "tags": []},
    ]


def test_assemble_scores_pass_fail_and_missing_trace_error():
    answers = {"c1": ("...", "t1"), "c2": ("...", "t2"), "c3": ("...", None)}
    out = assemble(_cases(), answers=answers, traces={"t1": _GROUNDED, "t2": _INVENTED},
                   judge=None, run_id="run1", set_name="golden", target="live",
                   baseline_run_id=None, now=_NOW)
    verdicts = {r["eval_case_id"]: r["verdict"] for r in out["results"]}
    assert verdicts == {"c1": "pass", "c2": "fail", "c3": "error"}
    agg = out["run_row"]["aggregates"]
    assert (agg["n"], agg["passed"], agg["failed"], agg["error"]) == (3, 1, 1, 1)
    assert agg["pass_rate"] == round(1 / 3, 3)
    assert out["run_row"]["model"] == "claude-haiku-4-5"      # captured from the first trace
    assert out["run_row"]["cost_usd"] > 0                     # summed from trace envelopes
    assert agg["by_tag"]["honesty"] == {"n": 2, "passed": 1}


def test_assemble_uses_the_injected_judge():
    case = [{"eval_case_id": "j1", "question": "plan for X?", "ui": {},
             "expected": {"graders": ["usefulness_judge"]}, "tags": ["usefulness"]}]
    body = _trace("tj", "Here is an actionable plan: do A, then B.")
    good = lambda p: '{"score": 0.95, "verdict": "pass", "rationale": "actionable"}'
    out = assemble(case, answers={"j1": ("...", "tj")}, traces={"tj": body}, judge=good,
                   run_id="r", set_name="golden", target="live", baseline_run_id=None, now=_NOW)
    r = out["results"][0]
    assert r["verdict"] == "pass" and r["judge_rationale"] == "actionable"


def test_run_wires_answer_fetch_and_write(monkeypatch):
    cases = [_cases()[0]]                                     # just c1 (grounded → pass)
    monkeypatch.setattr(re, "_load_active_cases", lambda: cases)
    monkeypatch.setattr(re, "_baseline", lambda target, set_name: None)
    monkeypatch.setattr(re, "_answer", lambda case, *, base_url, token: ("...", "t1"))
    monkeypatch.setattr(re, "_fetch_trace_jsonl", lambda uri: _GROUNDED)
    written: dict = {}
    monkeypatch.setattr(re, "_write", lambda run_row, results: written.update(
        run_row=run_row, results=results))
    out = re.run(set_name="golden", target="live", base_url="http://x", token="tok",
                 bucket="b", judge=None, now=_NOW)
    assert written["results"][0]["verdict"] == "pass"
    assert written["run_row"]["aggregates"]["passed"] == 1
    assert out["run_row"]["eval_run_id"]                     # a run id was minted


def test_run_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setattr(re, "_load_active_cases", lambda: [_cases()[0]])
    monkeypatch.setattr(re, "_baseline", lambda target, set_name: None)
    monkeypatch.setattr(re, "_answer", lambda case, *, base_url, token: ("...", "t1"))
    monkeypatch.setattr(re, "_fetch_trace_jsonl", lambda uri: _GROUNDED)
    called = {"wrote": False}
    monkeypatch.setattr(re, "_write", lambda *a, **k: called.update(wrote=True))
    re.run(set_name="golden", target="live", base_url="http://x", token="t", bucket="b",
           judge=None, now=_NOW, dry_run=True)
    assert called["wrote"] is False
