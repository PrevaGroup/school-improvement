"""measurement frames — which observations an estimate was fitted on, versioned and rebuildable

Three tables plus two triggers. The triggers exist because both invariants here are the kind that
survive exactly as long as nobody is in a hurry:

  * an ACTIVE frame's definition is immutable — an estimate quoted last month must stay
    attributable to the definition that produced it, so a change is a new version, not an edit
  * a tombstone marks every frame that admitted the subject `stale`, in the same transaction as
    the deletion, so re-estimation is a job rather than something discovered later

The estimator is not here. Fits, facet estimates, fit statistics and bias interactions arrive with
Phase 6, when there is something to fit. What this migration provides is the record any future
estimate will need to be reproducible from.

Revision ID: 0010
Revises: 0009
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_STATUSES = ("draft", "active", "stale", "superseded")


def upgrade() -> None:
    op.create_table(
        "estimation_frame",
        sa.Column("frame_id", sa.Text(), primary_key=True),
        sa.Column("frame_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("definition_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("description", sa.Text()),
        sa.Column("supersedes_frame_id", sa.Text(),
                  sa.ForeignKey("estimation_frame.frame_id")),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("member_count", sa.Integer()),
        sa.Column("stale_reason", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.UniqueConstraint("tenant_id", "frame_key", "version",
                            name="uq_estimation_frame_version"),
        sa.CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in _STATUSES) + ")",
                           name="ck_estimation_frame_status"),
    )
    op.create_index("ix_estimation_frame_key", "estimation_frame",
                    ["tenant_id", "frame_key", "status"])

    op.create_table(
        "estimation_frame_member",
        sa.Column("frame_id", sa.Text(), sa.ForeignKey("estimation_frame.frame_id"),
                  primary_key=True),
        sa.Column("event_id", sa.Text(), sa.ForeignKey("score_event.event_id"),
                  primary_key=True),
        sa.Column("enters_calibration", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
    )
    op.create_index("ix_estimation_frame_member_calibration", "estimation_frame_member",
                    ["frame_id", "enters_calibration"])
    op.create_index("ix_estimation_frame_member_event", "estimation_frame_member",
                    ["event_id"])

    op.create_table(
        "measurement_deletion_tombstone",
        sa.Column("tombstone_id", sa.Text(), primary_key=True),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("requested_by", sa.Text()),
        sa.Column("frames_marked_stale", sa.Integer()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.CheckConstraint("subject_type IN ('student','section','artifact')",
                           name="ck_measurement_tombstone_subject_type"),
    )
    op.create_index("ix_measurement_tombstone_subject", "measurement_deletion_tombstone",
                    ["tenant_id", "subject_type", "subject_id"])

    op.execute("""
    -- An active frame's definition is frozen. Status may move (active -> stale -> superseded) and
    -- the resolve bookkeeping may be filled in, but what the frame ADMITS cannot change: a number
    -- published against version 3 has to keep meaning what it meant.
    CREATE FUNCTION measurement_freeze_active_frame() RETURNS trigger AS $$
    BEGIN
        IF OLD.status IN ('active', 'stale', 'superseded') THEN
            IF NEW.definition IS DISTINCT FROM OLD.definition
               OR NEW.definition_hash IS DISTINCT FROM OLD.definition_hash
               OR NEW.frame_key IS DISTINCT FROM OLD.frame_key
               OR NEW.version IS DISTINCT FROM OLD.version THEN
                RAISE EXCEPTION
                  'estimation_frame %(%/v%) is % — its definition is frozen. Create a new version.',
                  OLD.frame_id, OLD.frame_key, OLD.version, OLD.status
                  USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_estimation_frame_freeze
        BEFORE UPDATE ON estimation_frame
        FOR EACH ROW EXECUTE FUNCTION measurement_freeze_active_frame();

    -- A tombstone marks every frame that admitted the subject stale, in the same transaction as
    -- the deletion. Doing it in a nightly sweep instead would leave a window in which a published
    -- figure silently rests on observations that no longer exist.
    CREATE FUNCTION measurement_tombstone_marks_frames_stale() RETURNS trigger AS $$
    DECLARE
        touched integer;
    BEGIN
        WITH affected AS (
            SELECT DISTINCT m.frame_id
              FROM estimation_frame_member m
              JOIN score_event e ON e.event_id = m.event_id
             WHERE (NEW.subject_type = 'student'  AND e.student_id  = NEW.subject_id)
                OR (NEW.subject_type = 'section'  AND e.section_id  = NEW.subject_id)
                OR (NEW.subject_type = 'artifact' AND e.artifact_id = NEW.subject_id)
        )
        UPDATE estimation_frame f
           SET status = 'stale',
               stale_reason = coalesce(f.stale_reason || '; ', '')
                              || 'deletion ' || NEW.tombstone_id
          FROM affected a
         WHERE f.frame_id = a.frame_id
           AND f.status = 'active';

        GET DIAGNOSTICS touched = ROW_COUNT;
        NEW.frames_marked_stale := touched;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_measurement_tombstone
        BEFORE INSERT ON measurement_deletion_tombstone
        FOR EACH ROW EXECUTE FUNCTION measurement_tombstone_marks_frames_stale();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS trg_measurement_tombstone ON measurement_deletion_tombstone;
    DROP FUNCTION IF EXISTS measurement_tombstone_marks_frames_stale();
    DROP TRIGGER IF EXISTS trg_estimation_frame_freeze ON estimation_frame;
    DROP FUNCTION IF EXISTS measurement_freeze_active_frame();
    """)
    op.drop_table("measurement_deletion_tombstone")
    op.drop_table("estimation_frame_member")
    op.drop_table("estimation_frame")
