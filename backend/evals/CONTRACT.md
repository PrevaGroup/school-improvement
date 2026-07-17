# evals — contract

What a rewrite of this module must preserve.

## Tables owned (writes; a rewrite must keep producing these shapes)

- `trace` — one row per chat turn; PK `trace_id` (UUIDv7). Envelope scalars + JSONB
  (`ui`, `versions`, `totals`), `question` verbatim, `gcs_uri` to the 90-day full payload.
- `eval_case` — PK `eval_case_id`; `status ∈ {candidate, active, retired}`;
  `source ∈ {'seed', 'mined:<trace_id>'}`.
- `eval_run` — PK `eval_run_id`; versions/target/baseline for delta reporting.
- `eval_result` — PK (`eval_run_id`, `eval_case_id`).
- `feedback` — PK `feedback_id`; schema-only in v1 (§8.5).

All carry `tenant_id` (default `'public'`) — RLS-ready, policies deliberately not enabled yet
(eval-trace-system.md §6).

## Reads

- **GCS**: `gs://<TRACES_BUCKET>/traces/v1/dt=YYYY-MM-DD/<trace_id>.jsonl` — the JSONL trace
  schema (envelope line + event lines) is a cross-module contract with `serving`'s
  `app/traces.py`. Vendor-neutral by invariant (§8.4): OTel GenAI names, normalized `stop`.
- **core**: `app.config.settings` (bucket name, migration DB URL), `app.models.base.Base`.
- (phase 3+) producers' tables via SQL for grader ground truth — never via import.

## Migrations owned

- `migrations/0006_eval_tables.py` (revision `0006`, down `0005`) — registered via
  `alembic.ini version_locations`; models imported by `migrations/env.py` and
  `tests/test_schema_inventory.py`.

## Serving surface

- None in v1. (`POST /api/feedback` arrives with the deferred thumbs decision, §8.5 —
  mounted in `app/main.py` like sip's ingest routes when it does.)
