"""plan_extraction — full extracted plan JSON as a public JSONB blob

Holds schema.ExtractedPlan verbatim (provenance quotes, funding text, proposed metric
links) that the minimal normalized plan_* tables drop. Public tier (SPSAs are published
documents), so NO row-level security — served without a tenant binding. This is the
serving source for the plan-content marts (e.g. attendance-plan comparison).

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_extraction",
        sa.Column("plan_id", sa.Text(), primary_key=True),
        sa.Column("school_id", sa.Text()),
        sa.Column("plan_year", sa.Text()),
        sa.Column("plan_type", sa.Text()),
        sa.Column("extracted_at", sa.Text()),
        sa.Column("document", postgresql.JSONB(), nullable=False),
    )
    # Index the join key; the table is public (no RLS).
    op.create_index("ix_plan_extraction_school_id", "plan_extraction", ["school_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_extraction_school_id", table_name="plan_extraction")
    op.drop_table("plan_extraction")
