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

from sqlalchemy import CheckConstraint, Float, Index, Integer, SmallInteger, Text, TIMESTAMP, text
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
    # mined from real traffic | seeded by hand | one arm of a paired comparison. Not bookkeeping:
    # a suite made only of seeded cases measures what its author thought to ask.
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="seeded")
    # Three of the five stop conditions are comparisons, not measurements — the same paper in
    # different company, with conventions errors added, or at two scrutiny levels. The interesting
    # number is a DELTA and neither arm alone means anything, so the pairing is a column rather
    # than something reconstructed from tags afterwards. Migration 0030.
    pair_id: Mapped[str | None] = mapped_column(Text)
    arm: Mapped[str | None] = mapped_column(Text)
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


class StopConditionFinding(Base):
    """What one run of one stop condition found. The audit record of whether release was allowed.

    Until this table the findings evaporated the moment they were computed, which made the most
    important question about a gate unanswerable: has it ever held, and when did it start failing?
    A green result with no history cannot be told apart from a check nobody has run since June.

    THE THRESHOLD IS COPIED, NOT REFERENCED. `threshold_value`, `agreed_by` and `agreed_on` record
    the number that was in force when the measurement was taken. Reading the current threshold
    instead would let somebody relax a line in January and have December's runs retroactively
    pass, which is exactly the "explained rather than acted on" failure the pre-commitment rule
    exists to prevent. Migration 0030.
    """
    __tablename__ = "eval_stop_condition"

    finding_id: Mapped[str] = mapped_column(Text, primary_key=True)
    eval_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    observed: Mapped[float | None] = mapped_column(Float)

    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    agreed_by: Mapped[str | None] = mapped_column(Text)
    agreed_on: Mapped[str | None] = mapped_column(Text)

    n: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    # The numbers under the number. A verdict with no breakdown is the uninformative summary that
    # `teacher_acceptance` exists to detect, arriving one layer up.
    breakdown: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="public")

    __table_args__ = (
        CheckConstraint("verdict IN ('holds','triggered','uncommitted','insufficient')",
                        name="verdict"),
        # The pre-commitment rule in the database, not only in Python: the module is one way to
        # write this table and a script is another. Same argument as the release trigger.
        CheckConstraint(
            "verdict <> 'triggered' OR (agreed_by IS NOT NULL AND agreed_on IS NOT NULL)",
            name="a_stop_names_who_agreed_to_it"),
        CheckConstraint("verdict <> 'insufficient' OR observed IS NULL",
                        name="insufficient_has_no_number"),
        Index("ix_eval_stop_condition_run", "eval_run_id", "condition"),
        Index("ix_eval_stop_condition_history", "tenant_id", "condition", "created_at"),
    )
