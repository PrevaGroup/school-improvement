"""intake tables — what a folder contained when it was read, and what each file turned out to be

Everything upstream of a score. A folder is read at a MOMENT, and that is the fact this schema is
built around: papers arrive late, students keep editing after the deadline, and a teacher presses
sync again. So a read is a `intake_manifest` row and every read produces a fresh one — the same
folder read twice is two manifests, not an update, and the difference between them is exactly the
question "what changed since I last looked".

## Why the extracted text lives here

`artifact.source_uri` pointed at a file on local disk, which worked because the pipeline ran as a
batch job on one machine. The review console runs on Cloud Run with no shared filesystem, and a
source that has moved or lost its permission leaves a reviewed artifact whose text nobody can read.
The text is extracted once, at read time, and stored — so everything downstream depends on a row
rather than on a mount.

It also makes re-reads answerable: `text_hash` changing for one `source_ref` is a student who kept
working, which is a NEW artifact superseding the old one under the same binding key, not an edit to
the one already scored.

## Five outcomes, and none of them is "missing"

A file is resolved, unresolved, not student work, unreadable, or empty. Those are five different
facts and a teacher acts differently on each. Collapsing any of them into an absence is how a
folder of twenty-seven files becomes a report of twenty-four scores with nobody asking about the
other three — the assignment prompt sitting in the folder is not a submission, and a document we
lack permission to open is an inventory discrepancy rather than a student who did not write.

`candidates` carries the near-misses for an unresolved file. The console's stuck queue is built on
it: "the document is owned by your template account, so we cannot read an author from it — editing
history points to one of three people" is this column rendered.

Revision ID: 0021
Revises: 0020
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

STATUSES = ("resolved", "unresolved", "not_student_work", "unreadable", "empty")


def upgrade() -> None:
    op.create_table(
        "intake_manifest",
        sa.Column("manifest_id", sa.Text(), primary_key=True),
        sa.Column("source_kind", sa.Text(), nullable=False),      # local | drive
        sa.Column("source_ref", sa.Text(), nullable=False),       # folder path or Drive folder id
        sa.Column("read_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("read_by", sa.Text()),
        # What the teacher DECLARED this folder is. Three of the four binding elements are a
        # declaration rather than an inference, and saying so is what keeps `resolution_path`
        # honest about which parts were actually worked out from evidence.
        sa.Column("declared_section_id", sa.Text()),
        sa.Column("declared_task_id", sa.Text()),
        sa.Column("declared_iteration", sa.Text()),
        sa.Column("declared_window_label", sa.Text()),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        # The integration-health signal. A rise means account matching stopped working, and it
        # shows up here before it shows up as a wrong score.
        sa.Column("inferred_rate", sa.Numeric()),
        sa.Column("run_id", sa.Text()),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.CheckConstraint("source_kind IN ('local','drive')", name="source_kind"),
    )
    op.create_index("ix_intake_manifest_source", "intake_manifest",
                    ["tenant_id", "source_ref", "read_at"])

    op.create_table(
        "intake_file",
        sa.Column("file_id", sa.Text(), primary_key=True),
        sa.Column("manifest_id", sa.Text(), sa.ForeignKey("intake_manifest.manifest_id"),
                  nullable=False),
        # Stable across reads: a Drive file id, or a path relative to the folder. This is what
        # makes "the same document, edited" distinguishable from "a new document".
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text()),
        sa.Column("modified_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("owner_email", sa.Text()),
        sa.Column("editor_emails", postgresql.JSONB()),

        sa.Column("text", sa.Text()),
        sa.Column("text_hash", sa.Text()),
        sa.Column("word_count", sa.Integer()),

        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text()),
        sa.Column("resolved_student_id", sa.Text()),
        # owner_account | editor_account | name — what evidence linked the file to a person, and
        # whether that was a lookup or an inference. A score whose binding was inferred has a
        # different error profile from one looked up, and pooling them pools two populations.
        sa.Column("resolution_basis", sa.Text()),
        sa.Column("resolution_path", sa.Text()),
        sa.Column("match_score", sa.Numeric()),
        # The near-misses, for the stuck queue: who this might be, and why we could not tell.
        sa.Column("candidates", postgresql.JSONB()),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in STATUSES) + ")", name="status"),
        # Resolved means a person was named. Anything else must not carry one, or a half-matched
        # file quietly becomes somebody's paper.
        sa.CheckConstraint(
            "(status = 'resolved') = (resolved_student_id IS NOT NULL)",
            name="resolved_names_a_student"),
        sa.UniqueConstraint("manifest_id", "source_ref", name="uq_intake_file_source_ref"),
    )
    op.create_index("ix_intake_file_manifest", "intake_file", ["manifest_id", "status"])
    op.create_index("ix_intake_file_hash", "intake_file", ["text_hash"])
    op.create_index("ix_intake_file_student", "intake_file",
                    ["tenant_id", "resolved_student_id"])


def downgrade() -> None:
    op.drop_table("intake_file")
    op.drop_table("intake_manifest")
