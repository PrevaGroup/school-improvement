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

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("TRUNCATE fact_metric, dim_school")
    # Migration 0001 builds the schema via create_all(), which tracks the *current*
    # models — so on a fresh DB dim_school already arrives in the new shape and there
    # is nothing to rename. Guard so this is a no-op there and a real re-key on an
    # already-deployed 0001-era DB (which still has cds_code).
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'dim_school' AND column_name = 'cds_code') THEN
                ALTER TABLE dim_school RENAME COLUMN cds_code TO state_school_id;
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE dim_school ADD COLUMN IF NOT EXISTS state_district_id TEXT")


def downgrade() -> None:
    op.execute("TRUNCATE fact_metric, dim_school")
    op.execute("ALTER TABLE dim_school DROP COLUMN IF EXISTS state_district_id")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'dim_school' AND column_name = 'state_school_id') THEN
                ALTER TABLE dim_school RENAME COLUMN state_school_id TO cds_code;
            END IF;
        END $$;
    """)
