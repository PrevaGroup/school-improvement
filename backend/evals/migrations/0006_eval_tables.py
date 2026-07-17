"""eval tables — the trace store + eval loop (evals module)

trace / eval_case / eval_run / eval_result / feedback. All carry tenant_id (server_default
'public') — RLS-READY but deliberately not RLS-ENABLED: every row is public-tenant today,
and the policy flip is core's deliberate move when chat first serves private plan data
(eval-trace-system.md §6). `feedback` is schema-only in v1 (§8.5) — no endpoint writes it yet.

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trace",
        sa.Column("trace_id", sa.Text(), primary_key=True),
        sa.Column("session_id", sa.Text()),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="public"),
        sa.Column("principal_hash", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("question", sa.Text()),
        sa.Column("ui", postgresql.JSONB()),
        sa.Column("provider", sa.Text()),
        sa.Column("model", sa.Text()),
        sa.Column("versions", postgresql.JSONB()),
        sa.Column("totals", postgresql.JSONB()),
        sa.Column("gcs_uri", sa.Text()),
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    # The miner's two scan axes: time windows, and failure classes within them (§4 step 1).
    op.create_index("ix_trace_ts", "trace", ["ts"])
    op.create_index("ix_trace_status_ts", "trace", ["status", "ts"])

    op.create_table(
        "eval_case",
        sa.Column("eval_case_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="public"),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("ui", postgresql.JSONB()),
        sa.Column("expected", postgresql.JSONB()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="candidate"),
        sa.Column("tags", postgresql.ARRAY(sa.Text())),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    op.create_table(
        "eval_run",
        sa.Column("eval_run_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="public"),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("set_name", sa.Text()),
        sa.Column("target", sa.Text()),
        sa.Column("provider", sa.Text()),
        sa.Column("model", sa.Text()),
        sa.Column("versions", postgresql.JSONB()),
        sa.Column("baseline_run_id", sa.Text()),
        sa.Column("aggregates", postgresql.JSONB()),
        sa.Column("cost_usd", sa.Float()),
    )

    op.create_table(
        "eval_result",
        sa.Column("eval_run_id", sa.Text(), primary_key=True),
        sa.Column("eval_case_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="public"),
        sa.Column("verdict", sa.Text()),
        sa.Column("scores", postgresql.JSONB()),
        sa.Column("judge_rationale", sa.Text()),
        sa.Column("trace_id", sa.Text()),
    )

    op.create_table(
        "feedback",
        sa.Column("feedback_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="public"),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("principal_hash", sa.Text()),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("eval_result")
    op.drop_table("eval_run")
    op.drop_table("eval_case")
    op.drop_index("ix_trace_status_ts", table_name="trace")
    op.drop_index("ix_trace_ts", table_name="trace")
    op.drop_table("trace")
