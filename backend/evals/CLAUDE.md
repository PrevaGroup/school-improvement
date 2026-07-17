# evals — module guardrails

You are working in the **evals** module: the trace store + eval loop
(design: `docs/design/eval-trace-system.md` — read §1–§4 and the §8 decisions first;
`README.md` here maps the components).

## Scope — what you may touch

- This module's code (`ingest_traces.py`, `_db.py`, future `run_evals` / `mine_traces` /
  graders), its 5 owned tables (`trace`, `eval_case`, `eval_run`, `eval_result`, `feedback`),
  their models in `models.py`, and DDL in `migrations/`.

## Hard rules

- **Never import `serving` (or any module) at runtime.** The eval runner exercises chat as an
  **HTTP client** against a deployed revision; graders read producers' tables with **SQL**.
  If you need code from `app/chat.py` or `app/traces.py`, stop — that's a design smell, raise
  it. (Tests are tooling and exempt: the JSONL contract cross-check imports `app.traces`
  deliberately.)
- **The JSONL trace schema is vendor-neutral and shared with `serving`'s emitter.** Never add
  a provider wire-format field (e.g. `stop_reason`) to what ingest expects — normalization is
  the emitter side's job (the vendor-agnostic invariant, §8.4).
- **Ingest is best-effort, idempotent, and unstoppable**: malformed objects are skipped and
  logged, never fatal; the insert stays `ON CONFLICT (trace_id) DO NOTHING`.
- **Question text is verbatim, forever (§8.3).** Never truncate, clean, or semantically shrink
  it at ingest — derived labels (`question_class`) are `mine_traces`' job, stored separately.
- **`tenant_id` stays on every table and every new one.** RLS policies are NOT yours to add —
  that flip is a deliberate core move when private data first flows (§6).
- **Feedback endpoint/UI is deliberately absent (§8.5).** Don't add it as a drive-by; it's a
  decision to reopen with the human.
- **Models must stay registered**: `migrations/env.py` and `tests/test_schema_inventory.py`
  both import `evals.models` — keep all three in sync (autogenerate reads an unseen table as
  DROP TABLE).
- **Eval runs must never eat the API budget**: the runner (phase 3) authenticates as its own
  principal so `usage_chat_daily` caps bound it. Don't bypass that with a raw Anthropic call.

## Definition of done

- `python -m pytest` green from `backend/` (module + boundary + schema-inventory tests).
- `alembic history` still shows ONE linear chain ending at your head (run it offline — cheap).
- New behavior has a test beside it in `tests/`.
