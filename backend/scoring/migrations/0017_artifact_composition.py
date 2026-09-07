"""scoring — the review packet, stored as the teacher saw it

Composition assembles what a teacher reviews: every criterion with its level, verified evidence and
reason; the criteria that need a human; and each criterion's prior observations for that student.

WHY THIS IS STORED RATHER THAN DERIVED ON READ. Almost all of it IS derivable from score_event, and
a stored copy of derivable data is normally a second source of truth waiting to drift. Here it is
not, for a specific reason: score_event is append-only, so a teacher override APPENDS a new event.
Re-deriving the packet after a review therefore produces a DIFFERENT packet than the one the
teacher was looking at when they decided. The packet is the record of what was actually in front of
a person at the moment they made a judgment, and that is not derivable from anything.

History is kept for the same reason — the latest row is current, and an earlier one is what someone
reviewed. Nothing is updated.

WHAT IS DELIBERATELY NOT HERE. The student-facing feedback draft. It is a model call against the
highest-stakes surface in the system, `artifact.state` has a `blocked` state waiting for the safety
check that gates it, and `models.py` and the review console currently disagree about whether that
draft exists before or after review. That contradiction should be resolved by a person, not settled
quietly by whichever file got written first.

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_composition",
        sa.Column("composition_id", sa.Text(), primary_key=True),
        sa.Column("artifact_id", sa.Text(), sa.ForeignKey("artifact.artifact_id"),
                  nullable=False),
        # Which assembler built it. A packet's shape is part of what a teacher saw.
        sa.Column("composer_version", sa.Text(), nullable=False),
        sa.Column("packet", postgresql.JSONB(), nullable=False),
        # Denormalised out of the packet because these two drive the queue, and a queue that has
        # to open every JSON blob to sort itself is a queue that gets slower with the year.
        sa.Column("needs_human", sa.Integer(), nullable=False, server_default="0"),
        # True when any prior observation shown came from a different scoring configuration. Raw
        # levels from two raters are not directly comparable, and a trend line drawn through them
        # is the growth claim the whole measurement design exists to qualify.
        sa.Column("prior_rater_mismatch", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("supersedes_composition_id", sa.Text(),
                  sa.ForeignKey("artifact_composition.composition_id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
    )
    op.create_index("ix_artifact_composition_artifact", "artifact_composition",
                    ["artifact_id", "created_at"])
    op.create_index("ix_artifact_composition_queue", "artifact_composition",
                    ["tenant_id", "needs_human"])

    # Same rule as score_event, for the same reason: this is a record of what someone saw, and a
    # record you can edit afterwards is not one.
    op.execute("""
    CREATE FUNCTION scoring_composition_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION
          'artifact_composition is append-only: % rejected. Recomposing writes a new row that '
          'references the one it replaces.', TG_OP
          USING ERRCODE = 'check_violation';
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_artifact_composition_append_only
        BEFORE UPDATE OR DELETE ON artifact_composition
        FOR EACH ROW EXECUTE FUNCTION scoring_composition_append_only();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS trg_artifact_composition_append_only ON artifact_composition;
    DROP FUNCTION IF EXISTS scoring_composition_append_only();
    """)
    op.drop_table("artifact_composition")
