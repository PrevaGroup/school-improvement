"""Miner tests: signal detection (pure) + the mine() wiring with seams patched."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import evals.mine_traces as mt
from evals.mine_traces import candidate_from, signals_for


def _trace(reply="ok", tool_calls=(), status="ok", question="q"):
    env = {"trace_id": "t", "status": status, "ui": {"level": "High"},
           "totals": {}, "gen_ai.request.model": "m"}
    events = [{"type": "turn_start", "question": question}]
    events += [{"type": "tool_call", **tc} for tc in tool_calls]
    events.append({"type": "turn_end", "reply": reply})
    return "\n".join(json.dumps(x) for x in [env, *events])


def test_bad_status_alone_is_a_signal():
    assert signals_for({"status": "error"}, None) == ["status:error"]
    assert signals_for({"status": "max_iters"}, None) == ["status:max_iters"]


def test_grader_failure_on_a_real_answer_is_a_signal():
    body = _trace(reply="The plan budgets $999,999.")            # invented number
    sig = signals_for({"status": "ok", "question": "budget?"}, body)
    assert "grader:numeric_provenance" in sig


def test_tool_error_signal():
    body = _trace(tool_calls=[{"name": "compare_to_peers", "input": {}, "output": {},
                               "error": "boom"}])
    assert "tool_error" in signals_for({"status": "ok", "question": "x"}, body)


def test_zero_tool_data_question_is_needs_tool_but_chit_chat_is_not():
    data = _trace(tool_calls=(), question="what is the chronic absenteeism rate?")
    assert "needs_tool" in signals_for({"status": "ok", "question": "chronic absenteeism rate?"}, data)
    chat = _trace(tool_calls=(), question="hello there")
    assert signals_for({"status": "ok", "question": "hello there"}, chat) == []


def test_clean_trace_is_not_a_candidate():
    body = _trace(reply="Wilson's rate is 23%.",
                  tool_calls=[{"name": "compare_to_peers", "input": {},
                               "output": {"target_value": 0.23}, "error": None}])
    assert signals_for({"status": "ok", "question": "rate?"}, body) == []
    assert candidate_from({"trace_id": "t", "status": "ok", "question": "rate?", "ui": {}}, body) is None


def test_candidate_id_is_deterministic_for_idempotent_remining():
    row = {"trace_id": "abc-123", "status": "error", "question": "q", "ui": {"level": "High"}}
    c = candidate_from(row, None)
    assert c["eval_case_id"] == "mined-abc-123"
    assert c["source"] == "mined:abc-123"
    assert "mined" in c["tags"] and "status:error" in c["tags"]
    assert json.loads(c["ui"]) == {"level": "High"}


def test_mine_wires_load_fetch_and_write(monkeypatch):
    rows = [{"trace_id": "t1", "status": "error", "question": "q", "ui": {}, "gcs_uri": None},
            {"trace_id": "t2", "status": "ok", "question": "rate?", "ui": {},
             "gcs_uri": "gs://b/x.jsonl"}]
    monkeypatch.setattr(mt, "_load_prod_traces", lambda since, limit: rows)
    monkeypatch.setattr(mt, "_fetch_trace_jsonl",
                        lambda uri, attempts=1: _trace(reply="Budget $999,999."))
    written: list = []
    monkeypatch.setattr(mt, "_write", lambda cands: written.extend(cands) or len(cands))
    counts = mine_counts = mt.mine(days=7, limit=10, now=datetime(2026, 7, 21, tzinfo=timezone.utc))
    assert counts["scanned"] == 2 and counts["candidates"] == 2   # t1 (status) + t2 (grader)
    assert {c["eval_case_id"] for c in written} == {"mined-t1", "mined-t2"}


def test_mine_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setattr(mt, "_load_prod_traces",
                        lambda since, limit: [{"trace_id": "t1", "status": "error",
                                               "question": "q", "ui": {}, "gcs_uri": None}])
    called = {"wrote": False}
    monkeypatch.setattr(mt, "_write", lambda cands: called.update(wrote=True) or 0)
    counts = mt.mine(days=1, now=datetime(2026, 7, 21, tzinfo=timezone.utc), dry_run=True)
    assert counts["candidates"] == 1 and counts["inserted"] == 1 and called["wrote"] is False
