# evals — trace store + continuous-improvement loop

The **store half** of the eval trace system ([design + all decisions](../../docs/design/eval-trace-system.md)):
`serving` emits each chat turn as a JSONL object to GCS (`app/traces.py` — no tables); this
module ingests those objects in batch and owns everything queryable. Phase 2 of the design —
later phases add `run_evals` (drives `/api/chat` as an HTTP client) and `mine_traces`
(failures/feedback → candidate eval cases).

## Component map

| Component | What it is |
|---|---|
| `models.py` | the 5 owned tables (below) — JSONB-heavy on purpose; see its docstring |
| `migrations/0006_eval_tables.py` | their DDL, wired via `alembic.ini version_locations` |
| `ingest_traces.py` | `python -m evals.ingest_traces` — GCS objects → `trace` rows, idempotent on trace_id |
| `_db.py` | this module's own engine (migrator role) — same pattern as sip's `_db.py` |
| `tests/` | parse/ingest logic + the emitter↔ingest JSONL contract cross-check |

## Owned tables (the contract)

| Table | Grain |
|---|---|
| `trace` | one chat turn (the envelope; full payload stays in GCS, 90 days) |
| `eval_case` | one curated question (`candidate → active → retired`; humans promote) |
| `eval_run` | one execution of a case set against one deployment target |
| `eval_result` | run × case |
| `feedback` | one 👍/👎 — **schema only in v1** (§8.5): no endpoint, no UI yet |

## Running ingest

Cloud Shell / Cloud Run job, never locally (it reaches Cloud SQL + GCS):

```
cd backend
python -m evals.ingest_traces            # re-scan last 3 day partitions (idempotent)
python -m evals.ingest_traces --date 2026-07-16
python -m evals.ingest_traces --dry-run  # parse + count, write nothing
```

No watermark by design: emission is fire-and-forget, so late objects land inside their
`dt=` partition; the 3-day overlap re-scan + `ON CONFLICT DO NOTHING` absorbs them.

**In production** this runs **hourly** as a Cloud Run Job (`sip-ingest-traces`) triggered by
Cloud Scheduler — job + trigger + the dedicated `eval-runner` service account are set up in
[`backend/DEPLOY.md`](../DEPLOY.md) (§ *Scheduling trace ingest*). Note the two non-obvious bits
that section covers: the job reaches Cloud SQL over the `/cloudsql/<ICN>` socket (this module's
`_db.py` has no Connector logic), and the SA needs `storage.objectViewer` to *read* the bucket
the app only *writes*.

## OpenTelemetry export (interoperability)

Our trace JSONL is deliberately **OTel-shaped**, so a trace exports to any OTLP-compatible
eval/observability backend (Phoenix, Langfuse, Braintrust) **without rework** — that portability
is the design's interoperability asset ([eval-trace-system.md §2](../../docs/design/eval-trace-system.md),
[eval-interoperability.md P5](../../docs/design/eval-interoperability.md)). Two things make it a
remap, not a reshape:

- Envelope/event fields already follow the **OTel GenAI semantic conventions**
  (`gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.*`).
- Every event already carries `trace_id` / `span_id` / `parent_span_id` — the trace *is* a span
  tree.

`otel_export.py` does the conversion (pure, unit-tested; no OTel SDK, no hot-path instrumentation
— we own the JSONL and convert on demand):

```
python -m evals.otel_export gs://<bucket>/traces/v1/dt=YYYY-MM-DD/<trace_id>.jsonl > spans.json
python -m evals.otel_export ./trace.jsonl            # a local object works too
```

It emits an OTLP/JSON `ResourceSpans` payload a collector accepts (POST to its traces endpoint).
The span tree: the **turn** is the root `chat {model}` SERVER span; each `model_call` is a child
`chat` CLIENT span; each `tool_call` is a child `execute_tool {name}` span.

| Our trace field | OTel span / attribute |
|---|---|
| envelope `trace_id` | `traceId` |
| event `span_id` / `parent_span_id` | `spanId` / `parentSpanId` |
| `gen_ai.provider.name`, `gen_ai.request.model` | same (GenAI semconv) |
| `totals.input_tokens` / `output_tokens` | `gen_ai.usage.input_tokens` / `output_tokens` |
| normalized `stop` (tool_use·end·max_tokens·refusal) | `gen_ai.response.finish_reasons` |
| `tool_call.name` | `gen_ai.tool.name` (op `execute_tool`) |
| `session_id` | `session.id` |
| `status` (ok·refusal·error·max_iters) | span `status` (unset·ok·error) |
| `ts` + `latency_ms` | `startTimeUnixNano` + `endTimeUnixNano` |

**The vendor-agnostic invariant holds here too:** the exporter reads only the neutral vocabulary
(the normalized `stop`, never a provider's `stop_reason`), so no wire-format field leaks into the
OTLP output. Same rule as the emitter (§8.4).

## How to change safely

1. The JSONL schema is a **cross-module contract** with `app/traces.py` (no shared code —
   the table seam's cousin). `tests/test_ingest_traces.py::test_the_real_recorder_and_the_ingest_parse_agree`
   is the tripwire; change either side only with both in view.
2. New envelope fields: prefer keys inside the existing JSONB columns (no migration) over new
   scalar columns (migration). Scalars are for what you filter/index on.
3. Never import another module at runtime (`serving` included) — the boundary test enforces it.
   Graders (phase 3+) get ground truth from producers' tables via SQL, the sanctioned seam.
