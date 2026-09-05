"""pooling seam — consent and run audit for the one job that crosses the district threshold

Two tables and no job. The job that fills the aggregate tables waits on a legal basis and on a
minimum district count; the seam does not, because the module boundary and the tenantless principal
are what would be expensive to retrofit and cost nothing now.

The aggregate tables themselves (agg_task_difficulty, agg_trait_profile, and the rest) are NOT
created here. Their grain follows from the PM console's data contract and from the suppression
parameters, and both are open — creating them now would freeze a shape before the questions that
determine it have answers.

Neither table carries `tenant_id`, and that is the point rather than an omission: they belong to no
district. The PM principal is deliberately unmapped to any tenant, so every district-scoped table
returns zero rows for it under RLS, and the failure mode of a routing mistake is an empty screen.

Revision ID: 0011
Revises: 0010
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pooling_aggregation_consent",
        sa.Column("consent_id", sa.Text(), primary_key=True),
        sa.Column("district_tenant_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("instrument_ref", sa.Text()),
        sa.Column("granted_by", sa.Text()),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("revocation_reason", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("district_tenant_id", "scope", "effective_from",
                            name="uq_pooling_consent_span"),
        sa.CheckConstraint("scope IN ('module_evidence','teacher_instrumentation')",
                           name="ck_pooling_consent_scope"),
    )
    op.create_index("ix_pooling_consent_district", "pooling_aggregation_consent",
                    ["district_tenant_id", "scope"])

    op.create_table(
        "pooling_aggregate_run",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("definition_key", sa.Text(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("frame_version", sa.Text()),
        sa.Column("configuration_version", sa.Text()),
        sa.Column("window_label", sa.Text()),
        sa.Column("consent_snapshot", postgresql.JSONB()),
        sa.Column("suppression_params", postgresql.JSONB()),
        sa.Column("district_count", sa.Integer()),
        sa.Column("cells_emitted", sa.Integer()),
        sa.Column("cells_suppressed", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("stale_reason", sa.Text()),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint("status IN ('running','succeeded','failed','superseded')",
                           name="ck_pooling_run_status"),
    )
    op.create_index("ix_pooling_run_definition", "pooling_aggregate_run",
                    ["definition_key", "window_label"])


def downgrade() -> None:
    op.drop_table("pooling_aggregate_run")
    op.drop_table("pooling_aggregation_consent")
