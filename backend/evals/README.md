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

## How to change safely

1. The JSONL schema is a **cross-module contract** with `app/traces.py` (no shared code —
   the table seam's cousin). `tests/test_ingest_traces.py::test_the_real_recorder_and_the_ingest_parse_agree`
   is the tripwire; change either side only with both in view.
2. New envelope fields: prefer keys inside the existing JSONB columns (no migration) over new
   scalar columns (migration). Scalars are for what you filter/index on.
3. Never import another module at runtime (`serving` included) — the boundary test enforces it.
   Graders (phase 3+) get ground truth from producers' tables via SQL, the sanctioned seam.
