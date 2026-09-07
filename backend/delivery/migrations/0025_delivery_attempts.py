"""delivery — what happened after a teacher said yes

`released` means a teacher approved a message. Until now nothing happened next, which is the
product stopping one step short of its purpose: the feedback exists, is correct, is signed off,
and never reaches the student it was written for.

## An attempt is a fact, so every one is a row

Including the failures. The plan is explicit — "failures recorded as failures" — and the reason is
that a delivery which silently did not happen is indistinguishable from one that did, from every
screen a teacher looks at. Twenty-six students got their feedback and two did not, and nobody
knows which two.

So this table is append-only, a retry is a NEW row, and the current state of a hand-back is the
latest attempt rather than a column somebody updates. The history is the point: "we tried at
09:41, the document had been moved, we tried again at 14:02 and it went" is what a teacher needs
when a student says they never got anything.

## Delivery is not a state of the artifact

`artifact.state` ends at `released`, and it stays that way. A teacher's decision and what happened
to the network afterwards are different kinds of fact: the first is a judgment that cannot fail,
the second is an I/O operation that fails routinely. Folding a delivery failure into the state
machine would mean a transient network error moving a paper out of `released`, which would then
need a transition back — and a state machine with a retry loop in it is not a record of decisions
any more.

## The channel is recorded because it will change

The plan names two real ones — comments on the student's own document, or Classroom — and neither
requires the student to sign in, which is what keeps a large consent and minor-account surface out
of the pilot. `file` is the prototype's: it writes beside the paper, which is verifiable in a
local-folder demo and is real delivery to a real place. Recording which one carried a
message means a hand-back from before the integration existed is still legible afterwards, rather
than looking like a Drive delivery that left no trace.

Revision ID: 0025
Revises: 0024
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# `queued` is the mockup's "approved, waiting to go out" — a teacher who hands back at the end of
# the lesson has approved something that has deliberately not gone yet, and that is not a failure.
STATUSES = ("queued", "sent", "failed", "not_sent")
# The plan names two real ones: "Feedback is delivered as comments on the student's own document,
# or through Classroom; the student never signs in." `file` is the prototype's — it writes beside
# the paper, which is verifiable in a local-folder demo and is real delivery to a real place.
CHANNELS = ("file", "google_docs_comment", "classroom", "none")


def upgrade() -> None:
    op.create_table(
        "artifact_delivery",
        sa.Column("delivery_id", sa.Text(), primary_key=True),
        sa.Column("artifact_id", sa.Text(), sa.ForeignKey("artifact.artifact_id"),
                  nullable=False),
        # WHICH message went. A composition is superseded when a teacher edits, so a delivery that
        # only named the artifact could not answer "what did the student actually read".
        sa.Column("composition_id", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("target_ref", sa.Text()),          # the path, the Drive file id, the comment id
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text()),              # the failure, in the words of whatever failed
        # A hash of what was sent. If a message is edited after delivery, this is what proves the
        # student read the earlier one.
        sa.Column("message_hash", sa.Text()),
        sa.Column("attempted_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("attempted_by", sa.Text()),
        sa.Column("supersedes_delivery_id", sa.Text(),
                  sa.ForeignKey("artifact_delivery.delivery_id")),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in STATUSES) + ")",
                           name="status"),
        sa.CheckConstraint("channel IN (" + ",".join(f"'{c}'" for c in CHANNELS) + ")",
                           name="channel"),
        # Sent means it arrived somewhere and we know when. A `sent` row with no timestamp and no
        # target is a claim with nothing behind it.
        sa.CheckConstraint(
            "status <> 'sent' OR (delivered_at IS NOT NULL AND target_ref IS NOT NULL)",
            name="sent_says_where_and_when"),
        # A failure that does not say what went wrong is indistinguishable from one nobody looked
        # at, and it is the row somebody reads at 8am when a student is standing in front of them.
        sa.CheckConstraint("status <> 'failed' OR detail IS NOT NULL",
                           name="a_failure_says_what_failed"),
    )
    op.create_index("ix_artifact_delivery_artifact", "artifact_delivery",
                    ["artifact_id", "attempted_at"])
    op.create_index("ix_artifact_delivery_queue", "artifact_delivery",
                    ["tenant_id", "status", "attempted_at"])

    op.execute("""
    -- Append-only, like every other record in this subsystem. A retry writes a new row pointing
    -- at the one it follows; editing an attempt would erase the fact that a delivery once failed,
    -- which is exactly the fact a teacher needs when a student says they got nothing.
    CREATE FUNCTION delivery_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION
          'artifact_delivery is append-only: % rejected. A retry is a new attempt, and the one '
          'that failed stays in the record.', TG_OP
          USING ERRCODE = 'check_violation';
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_artifact_delivery_append_only
        BEFORE UPDATE OR DELETE ON artifact_delivery
        FOR EACH ROW EXECUTE FUNCTION delivery_append_only();

    -- Nothing goes out that a teacher has not released. The console is one way to reach this
    -- table and a script is another, so the rule lives here rather than in whichever path is
    -- fashionable — the same reason the release authority is a trigger and not an if-statement.
    CREATE FUNCTION delivery_requires_release() RETURNS trigger AS $$
    DECLARE artifact_state text;
    BEGIN
        SELECT a.state INTO artifact_state FROM artifact a WHERE a.artifact_id = NEW.artifact_id;
        IF artifact_state <> 'released' THEN
            RAISE EXCEPTION
              'artifact % is in state %, not released — nothing is handed back that a teacher has '
              'not approved.', NEW.artifact_id, artifact_state
              USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_artifact_delivery_released
        BEFORE INSERT ON artifact_delivery
        FOR EACH ROW EXECUTE FUNCTION delivery_requires_release();
    """)

    op.execute("GRANT SELECT, INSERT ON artifact_delivery TO sip_app;")


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS trg_artifact_delivery_released ON artifact_delivery;
    DROP FUNCTION IF EXISTS delivery_requires_release();
    DROP TRIGGER IF EXISTS trg_artifact_delivery_append_only ON artifact_delivery;
    DROP FUNCTION IF EXISTS delivery_append_only();
    """)
    op.drop_table("artifact_delivery")
