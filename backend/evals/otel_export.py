"""Export a trace to OpenTelemetry (OTLP/JSON) — the interoperability proof (P5).

    python -m evals.otel_export gs://<bucket>/traces/v1/dt=YYYY-MM-DD/<trace_id>.jsonl
    python -m evals.otel_export ./some_trace.jsonl > spans.json

Our trace JSONL (docs/design/eval-trace-system.md §2) is already OTel-shaped: field names follow
the **OpenTelemetry GenAI semantic conventions** (`gen_ai.provider.name`, `gen_ai.request.model`,
`gen_ai.usage.*`), and every event already carries `trace_id` / `span_id` / `parent_span_id`. So a
trace is a span tree *waiting* to be OTLP — this module does the remap, no OTel SDK, no
instrumentation on the hot path. The point is portability: the same trace exports to any
OTLP-compatible eval/observability backend (Phoenix, Langfuse, Braintrust) without rework.

Pure and unit-tested: `spans_from_bundle` (Bundle → semconv-attributed spans) and `otlp_json`
(spans → an OTLP/JSON `ResourceSpans` payload a collector accepts). The CLI is a thin IO shell.

This module READS traces (like the graders); it never emits — emission stays serving's, in the
neutral vocabulary. Nothing here imports serving.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime

from .graders import Bundle, bundle_from_jsonl

log = logging.getLogger("evals.otel_export")

# OTel span status codes (UNSET=0, OK=1, ERROR=2) and a coarse map from our turn status.
_STATUS = {"ok": 1, "refusal": 1, "error": 2, "max_iters": 2}


def _unix_nano(ts: str | None) -> int | None:
    """ISO-8601 timestamp → Unix nanoseconds (OTLP's time unit). None passes through."""
    if not ts:
        return None
    try:
        return int(datetime.fromisoformat(ts).timestamp() * 1_000_000_000)
    except (ValueError, TypeError):
        return None


def _span(trace_id, span_id, parent_span_id, name, kind, start, end, attrs, status):
    """One intermediate span (readable; `otlp_json` encodes it to wire OTLP). `attrs` is a plain
    dict — None values are dropped so an absent field is simply absent, not a null attribute."""
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "name": name,
        "kind": kind,                                   # SERVER (turn) | CLIENT (model/tool call)
        "start_unix_nano": start,
        "end_unix_nano": end,
        "attributes": {k: v for k, v in attrs.items() if v is not None},
        "status": status,                               # 0 unset · 1 ok · 2 error
    }


def spans_from_bundle(bundle: Bundle) -> list[dict]:
    """Bundle → a span tree with OTel GenAI semconv attributes.

    Root span = the turn (`chat {model}`); children = each `model_call` (`chat`) and `tool_call`
    (`execute_tool {name}`), parented by `parent_span_id` exactly as recorded. Timings come from
    each event's `ts` + `latency_ms`; where absent, the span is instantaneous rather than invented.
    """
    env = bundle.envelope
    trace_id = env.get("trace_id")
    provider = env.get("gen_ai.provider.name")
    model = env.get("gen_ai.request.model")
    totals = bundle.totals or {}
    root_id = next((e.get("span_id") for e in bundle.events
                    if e.get("type") == "turn_start"), None)
    start = _unix_nano(env.get("ts"))
    end = (start + int(env["latency_ms"]) * 1_000_000
           if start is not None and env.get("latency_ms") is not None else start)

    spans = [_span(
        trace_id, root_id, None, f"chat {model}".strip(), "SERVER", start, end,
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": provider,
            "gen_ai.request.model": model,
            "gen_ai.usage.input_tokens": totals.get("input_tokens"),
            "gen_ai.usage.output_tokens": totals.get("output_tokens"),
            "gen_ai.usage.cost_usd_est": totals.get("cost_usd_est"),
            "session.id": env.get("session_id"),
            "sip.source": env.get("source"),
            "sip.tenant_id": env.get("tenant_id"),
        },
        _STATUS.get(bundle.status, 0),
    )]

    for e in bundle.events:
        et = e.get("type")
        e_start = _unix_nano(e.get("ts"))
        e_end = (e_start + int(e["latency_ms"]) * 1_000_000
                 if e_start is not None and e.get("latency_ms") is not None else e_start)
        if et == "model_call":
            usage = e.get("usage") or {}
            spans.append(_span(
                trace_id, e.get("span_id"), e.get("parent_span_id"),
                f"chat {model}".strip(), "CLIENT", e_start, e_end,
                {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.provider.name": provider,
                    "gen_ai.request.model": model,
                    "gen_ai.usage.input_tokens": usage.get("input_tokens"),
                    "gen_ai.usage.output_tokens": usage.get("output_tokens"),
                    # our normalized `stop` (tool_use·end·max_tokens·refusal) is the semconv
                    # finish_reasons list — already provider-neutral, so no wire value leaks here.
                    "gen_ai.response.finish_reasons": [e["stop"]] if e.get("stop") else None,
                },
                0,
            ))
        elif et == "tool_call":
            spans.append(_span(
                trace_id, e.get("span_id"), e.get("parent_span_id"),
                f"execute_tool {e.get('name')}".strip(), "CLIENT", e_start, e_end,
                {
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": e.get("name"),
                    "error.type": "tool_error" if e.get("error") else None,
                },
                2 if e.get("error") else 0,
            ))
    return spans


# --- OTLP/JSON encoding ------------------------------------------------------------------------
# https://opentelemetry.io/docs/specs/otlp/ — a collector accepts this over the traces endpoint.


def _attr(k: str, v):
    """One OTLP KeyValue with the right typed value (the wire format is type-tagged)."""
    if isinstance(v, bool):
        val = {"boolValue": v}
    elif isinstance(v, int):
        val = {"intValue": str(v)}                      # OTLP ints ride as strings
    elif isinstance(v, float):
        val = {"doubleValue": v}
    elif isinstance(v, list):
        val = {"arrayValue": {"values": [{"stringValue": str(x)} for x in v]}}
    else:
        val = {"stringValue": str(v)}
    return {"key": k, "value": val}


def otlp_json(spans: list[dict], *, service_name: str = "sip-chat") -> dict:
    """Wrap intermediate spans into an OTLP/JSON `ResourceSpans` payload (a collector accepts it).
    16-byte trace ids / 8-byte span ids ride as hex, which is what our UUIDv7 trace_id and random
    span ids already are."""
    otlp_spans = []
    for s in spans:
        span = {
            "traceId": s["trace_id"],
            "spanId": s["span_id"],
            "name": s["name"],
            "kind": {"SERVER": 2, "CLIENT": 3}.get(s["kind"], 1),
            "attributes": [_attr(k, v) for k, v in s["attributes"].items()],
            "status": {"code": s["status"]},
        }
        if s.get("parent_span_id"):
            span["parentSpanId"] = s["parent_span_id"]
        if s.get("start_unix_nano") is not None:
            span["startTimeUnixNano"] = str(s["start_unix_nano"])
        if s.get("end_unix_nano") is not None:
            span["endTimeUnixNano"] = str(s["end_unix_nano"])
        otlp_spans.append(span)
    return {"resourceSpans": [{
        "resource": {"attributes": [_attr("service.name", service_name)]},
        "scopeSpans": [{"scope": {"name": "sip.evals.otel_export"}, "spans": otlp_spans}],
    }]}


def otlp_from_jsonl(body: str, *, service_name: str = "sip-chat") -> dict:
    """Raw trace JSONL string → OTLP/JSON payload."""
    return otlp_json(spans_from_bundle(bundle_from_jsonl(body)), service_name=service_name)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("uri", help="a trace JSONL: a local path or gs://<bucket>/traces/v1/…/<id>.jsonl")
    ap.add_argument("--service-name", default="sip-chat")
    args = ap.parse_args()

    import fsspec
    with fsspec.open(args.uri, "r") as f:
        body = f.read()
    print(json.dumps(otlp_from_jsonl(body, service_name=args.service_name), indent=2))


if __name__ == "__main__":
    main()
