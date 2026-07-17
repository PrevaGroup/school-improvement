"""The five tables the `evals` module owns — the store half of the eval trace system.

Design: docs/design/eval-trace-system.md (§1 architecture, §3 tables, §8 decisions).
`serving` EMITS traces to GCS and owns nothing; this module ingests them in batch
(`ingest_traces.py`) and owns everything queryable. GCS is the source of truth for full
payloads (tool outputs can be an entire SPSA); `trace` holds the envelope + `gcs_uri`.

Shape notes:

- **JSONB-heavy on purpose.** Traces are an evolving event stream — the reason these tables
  are NOT core-owned (§8.1 vs the `usage_chat_daily` precedent). The envelope's structured
  scalars get columns (queryable, indexable); everything that will grow with the agent loop
  (`ui`, `versions`, `totals`, grader params/scores) stays JSONB so a new capability is a new
  key, not a migration.
- **`tenant_id` on every table, from day one (§6).** Everything is 'public' today; the moment
  chat serves private plan data, these tables get the same RLS policies as `plan_*` — the
  schema is ready, only policies + the emission field flip. Deliberately NOT in core's
  PRIVATE_TABLES yet: there is no private row to protect, and RLS policy generation is
  core's seam to flip deliberately, not a side effect of this module existing.
- **`question` is kept indefinitely (decision §8.3)** — verbatim, never semantically shrunk
  (the mess is signal). Revisit at volume growth or private tenant data.
- **No FK from `feedback.trace_id` / `eval_result.trace_id` to `trace`**: traces arrive by
  batch ingest, so a rating or eval result can legitimately precede its trace row. The join
  is by value, tolerant of ingest lag.

REGISTRATION — same trap as every module's models (see likeschools/models.py):
    these classes reach `Base.metadata` only if imported. BOTH `migrations/env.py` and
    `tests/test_schema_inventory.py` must import this module, or autogenerate reads the
    tables as DROP TABLE. Guarded by test_schema_inventory.py.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Integer, SmallInteger, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Trace(Base):
    """One chat turn's envelope — ingested verbatim from the first JSONL line in GCS.

    The GCS object (envelope + full event stream, incl. complete tool outputs) is the
    source of truth and lives 90 days (bucket lifecycle); this row is the indefinitely-kept
    queryable summary. Graders that need full payloads fetch `gcs_uri`.
    """
    __tablename__ = "trace"
    trace_id: Mapped[str] = mapped_column(Text, primary_key=True)     # UUIDv7 (time-ordered)
    session_id: Mapped[str | None] = mapped_column(Text)              # client-declared continuity
    ts: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)         # ok·refusal·error·max_iters
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="public")
    principal_hash: Mapped[str | None] = mapped_column(Text)          # salted; never raw, never email
    source: Mapped[str] = mapped_column(Text, nullable=False)         # prod · eval
    question: Mapped[str | None] = mapped_column(Text)                # verbatim (§8.3), from turn_start
    ui: Mapped[dict | None] = mapped_column(JSONB)                    # {level, ...} — server-side scope
    provider: Mapped[str | None] = mapped_column(Text)                # gen_ai.provider.name
    model: Mapped[str | None] = mapped_column(Text)                   # gen_ai.request.model
    versions: Mapped[dict | None] = mapped_column(JSONB)              # git_sha/prompt/tool_catalog hashes
    totals: Mapped[dict | None] = mapped_column(JSONB)                # tokens by kind, cost_usd_est, iterations
    gcs_uri: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class EvalCase(Base):
    """One curated question the system must keep getting right."""
    __tablename__ = "eval_case"
    eval_case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="public")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    ui: Mapped[dict | None] = mapped_column(JSONB)                    # context the runner replays
    expected: Mapped[dict | None] = mapped_column(JSONB)              # graders to run + params, ground-truth refs
    source: Mapped[str] = mapped_column(Text, nullable=False)         # 'seed' | 'mined:<trace_id>'
    status: Mapped[str] = mapped_column(Text, nullable=False,         # candidate -> active -> retired;
                                        server_default="candidate")   # a human promotes (and scrubs, §6)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))       # 'honesty', 'tool:<name>', 'equity', ...
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


class EvalRun(Base):
    """One execution of a case set against one deployment target."""
    __tablename__ = "eval_run"
    eval_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="public")
    ts: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    set_name: Mapped[str | None] = mapped_column(Text)                # golden · full
    target: Mapped[str | None] = mapped_column(Text)                  # revision-tag URL or live (§8.2)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    versions: Mapped[dict | None] = mapped_column(JSONB)              # what ran: git_sha/prompt/catalog/rubric
    baseline_run_id: Mapped[str | None] = mapped_column(Text)         # deltas over absolutes (§4)
    aggregates: Mapped[dict | None] = mapped_column(JSONB)            # pass rates by tier/tag
    cost_usd: Mapped[float | None] = mapped_column(Float)


class EvalResult(Base):
    """run × case: how one case scored in one run. Every eval answer is itself a trace."""
    __tablename__ = "eval_result"
    eval_run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    eval_case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="public")
    verdict: Mapped[str | None] = mapped_column(Text)                 # pass · fail · error
    scores: Mapped[dict | None] = mapped_column(JSONB)                # per-grader
    judge_rationale: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)                # the eval turn's own trace


class Feedback(Base):
    """One 👍/👎 on a chat answer. SCHEMA ONLY in v1 (decision §8.5): the POST /api/feedback
    endpoint + UI thumbs are deferred — the table ships now so adding them later is a route,
    not a migration."""
    __tablename__ = "feedback"
    feedback_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="public")
    trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # +1 / -1
    comment: Mapped[str | None] = mapped_column(Text)
    principal_hash: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                         server_default=text("now()"))
