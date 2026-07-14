"""peer tables — "Schools Like You" input-matched peer groups (public marts)

feat_match_vector / mart_school_peer / model_partition_stats. All PUBLIC (no RLS):
computed from the public school universe, identical for every tenant — the similarity
artifact sits on the public side of the tenancy seam (spec §5.2 D9). See
backend/likeschools/school-classification-spec.md.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feat_match_vector",
        sa.Column("school_id", sa.Text(), primary_key=True),
        sa.Column("school_year", sa.Text(), primary_key=True),
        sa.Column("level_bucket", sa.Text()),
        sa.Column("f_econ_disadv", sa.Float()),
        sa.Column("f_el", sa.Float()),
        sa.Column("f_swd", sa.Float()),
        sa.Column("f_enroll_log", sa.Float()),
        sa.Column("f_locale_city", sa.Float()),
        sa.Column("f_locale_suburb", sa.Float()),
        sa.Column("f_locale_town", sa.Float()),
        sa.Column("f_locale_rural", sa.Float()),
        sa.Column("n_imputed", sa.SmallInteger(), server_default="0", nullable=False),
    )

    op.create_table(
        "mart_school_peer",
        sa.Column("school_id", sa.Text(), primary_key=True),
        sa.Column("peer_school_id", sa.Text(), primary_key=True),
        sa.Column("school_year", sa.Text(), primary_key=True),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("level_bucket", sa.Text()),
        sa.Column("low_confidence", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("ix_mart_school_peer_lookup", "mart_school_peer", ["school_id", "school_year", "rank"])

    op.create_table(
        "model_partition_stats",
        sa.Column("school_year", sa.Text(), primary_key=True),
        sa.Column("level_bucket", sa.Text(), primary_key=True),
        sa.Column("feature_names", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("means", postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column("sds", postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column("shrinkage", sa.Float()),
        sa.Column("precision_mat", postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column("k", sa.SmallInteger()),
        sa.Column("built_at", sa.TIMESTAMP(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("model_partition_stats")
    op.drop_index("ix_mart_school_peer_lookup", table_name="mart_school_peer")
    op.drop_table("mart_school_peer")
    op.drop_table("feat_match_vector")
