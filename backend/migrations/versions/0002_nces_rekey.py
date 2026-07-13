"""re-key school identity on federal NCES ids

`dim_school.school_id` becomes the 12-digit NCES 'Fed ID' (was the 14-digit CA CDS),
`district_id` its 7-digit LEAID prefix. The CDS moves to `state_school_id`
(renamed from `cds_code`) and a new `state_district_id`.

Because `school_id` re-keys, the previously loaded CDS-keyed rows are stale — this
truncates `fact_metric` and `dim_school` so the loaders repopulate them on the new
key. The data is fully reproducible from the raw CDE files (see etl/ca), so nothing
is lost. `fact_metric.school_id` FK-references `dim_school`, so both truncate together.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("TRUNCATE fact_metric, dim_school")
    op.alter_column("dim_school", "cds_code", new_column_name="state_school_id")
    op.add_column("dim_school", sa.Column("state_district_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("TRUNCATE fact_metric, dim_school")
    op.drop_column("dim_school", "state_district_id")
    op.alter_column("dim_school", "state_school_id", new_column_name="cds_code")
