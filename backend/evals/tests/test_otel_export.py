"""OTel export tests — pure, no IO. The trace JSONL is already span-structured (trace_id /
span_id / parent_span_id per event) and OTel-named, so export is a remap; these pin that it
stays a valid span tree with GenAI semconv attributes and encodes to OTLP/JSON a collector takes.
"""
from __future__ import annotations

from evals.otel_export import otlp_from_jsonl, otlp_json, spans_from_bundle
from evals.graders import bundle_from_lines

_LINES = [
    {"trace_id": "0195c3a2b7d47c9e8f10111213141516", "session_id": "sess-1", "ts": "2026-07-22T18:00:00+00:00",
     "latency_ms": 1200, "status": "ok", "source": "prod", "tenant_id": "public",
     "gen_ai.provider.name": "anthropic", "gen_ai.request.model": "claude-haiku-4-5",
     "totals": {"input_tokens": 900, "output_tokens": 120, "cost_usd_est": 0.0031}},
    {"type": "turn_start", "span_id": "aaaaaaaaaaaaaaaa", "parent_span_id": None,
     "ts": "2026-07-22T18:00:00+00:00", "question": "how is Wilson?"},
    {"type": "model_call", "span_id": "bbbbbbbbbbbbbbbb", "parent_span_id": "aaaaaaaaaaaaaaaa",
     "ts": "2026-07-22T18:00:00.100+00:00", "latency_ms": 400, "stop": "tool_use",
     "usage": {"input_tokens": 900, "output_tokens": 40}},
    {"type": "tool_call", "span_id": "cccccccccccccccc", "parent_span_id": "aaaaaaaaaaaaaaaa",
     "ts": "2026-07-22T18:00:00.600+00:00", "latency_ms": 50, "name": "compare_to_peers",
     "input": {"school_name": "Wilson"}, "output": {"target_value": 0.23}, "error": None},
    {"type": "turn_end", "span_id": "dddddddddddddddd", "parent_span_id": "aaaaaaaaaaaaaaaa",
     "ts": "2026-07-22T18:00:01.200+00:00", "reply": "Wilson's rate is 23%."},
]


def _spans():
    return spans_from_bundle(bundle_from_lines(_LINES))


def test_root_span_is_the_turn_with_genai_attributes():
    root = _spans()[0]
    assert root["parent_span_id"] is None and root["kind"] == "SERVER"
    a = root["attributes"]
    assert a["gen_ai.operation.name"] == "chat"
    assert a["gen_ai.provider.name"] == "anthropic"
    assert a["gen_ai.request.model"] == "claude-haiku-4-5"
    assert a["gen_ai.usage.input_tokens"] == 900 and a["gen_ai.usage.output_tokens"] == 120
    assert a["session.id"] == "sess-1"
    assert root["status"] == 1                          # ok


def test_model_and_tool_calls_become_child_spans():
    spans = _spans()
    by_id = {s["span_id"]: s for s in spans}
    model = by_id["bbbbbbbbbbbbbbbb"]
    assert model["parent_span_id"] == "aaaaaaaaaaaaaaaa"
    assert model["attributes"]["gen_ai.response.finish_reasons"] == ["tool_use"]
    tool = by_id["cccccccccccccccc"]
    assert tool["attributes"]["gen_ai.operation.name"] == "execute_tool"
    assert tool["attributes"]["gen_ai.tool.name"] == "compare_to_peers"


def test_tool_error_sets_error_status():
    lines = [dict(x) for x in _LINES]
    lines[3] = {**lines[3], "error": "boom"}
    spans = spans_from_bundle(bundle_from_lines(lines))
    tool = next(s for s in spans if s["attributes"].get("gen_ai.tool.name") == "compare_to_peers")
    assert tool["status"] == 2 and tool["attributes"]["error.type"] == "tool_error"


def test_timestamps_convert_to_unix_nanos_and_span_latency():
    root = _spans()[0]
    # 2026-07-22T18:00:00Z + 1200ms → end is 1.2e9 ns after start
    assert root["end_unix_nano"] - root["start_unix_nano"] == 1_200_000_000


def test_otlp_json_is_wire_shaped():
    payload = otlp_from_jsonl(__import__("json").dumps(_LINES[0]) + "\n"
                              + "\n".join(__import__("json").dumps(x) for x in _LINES[1:]))
    rs = payload["resourceSpans"][0]
    assert any(a["key"] == "service.name" for a in rs["resource"]["attributes"])
    spans = rs["scopeSpans"][0]["spans"]
    root = spans[0]
    assert root["traceId"] == "0195c3a2b7d47c9e8f10111213141516"
    assert "parentSpanId" not in root                   # root has none
    # int attributes ride as strings; token count is present and typed
    tok = next(a for a in root["attributes"] if a["key"] == "gen_ai.usage.input_tokens")
    assert tok["value"] == {"intValue": "900"}
    assert isinstance(root["startTimeUnixNano"], str)


def test_otlp_json_encodes_finish_reasons_as_array():
    payload = otlp_json(_spans())
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    model = next(s for s in spans if s["spanId"] == "bbbbbbbbbbbbbbbb")
    fr = next(a for a in model["attributes"] if a["key"] == "gen_ai.response.finish_reasons")
    assert fr["value"] == {"arrayValue": {"values": [{"stringValue": "tool_use"}]}}
