"""The two tables `intake` owns — what a folder contained when it was read.

Design: agentic-scoring-pipeline-design v0.06 §3.4 (binding), and the review console's stuck queue.

A folder is read at a MOMENT. Papers arrive late, students keep editing after the deadline, and a
teacher presses sync again — so every read is a new manifest rather than an update, and the
difference between two manifests is exactly the question "what changed since I last looked".

WHERE THE BOUNDARY SITS. `intake` reads folders, extracts text, and works out whose each file is.
It does NOT create artifacts: `artifact` belongs to `scoring`, and `scoring/bind.py` reads these
tables with SQL to make them. That is the producer/consumer cut, and it means the writes only ever
run one way — intake never touches an artifact, scoring never touches an intake row.

REGISTRATION — these classes only reach `Base.metadata` if something imports this module:
    * migrations/env.py                          -> autogenerate; unseen table means DROP TABLE
    * backend/tests/test_schema_inventory.py     -> mirrors that import list
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, Text, TIMESTAMP
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.tenant import TenantMixin

# Five outcomes, and none of them is "missing". A teacher acts differently on each, and collapsing
# any into an absence is how twenty-seven files become twenty-four scores with nobody asking about
# the other three.
FILE_STATUSES: tuple[str, ...] = (
    "resolved",          # a student was named, by account or by name
    "unresolved",        # we could not tell whose it is — candidates recorded
    "not_student_work",  # the prompt or a blank template. Worth keeping: it is the task statement
    "unreadable",        # permission or format — an inventory discrepancy, not an absence
    "empty",             # opened fine, contains nothing
)


class Manifest(Base, TenantMixin):
    """One read of one folder.

    The declared fields are the teacher's assertion about what this folder IS — section, task,
    iteration, window. Three of the four binding elements are a declaration rather than an
    inference, and recording that distinction is what keeps `resolution_path` honest about which
    part was actually worked out from evidence.
    """
    __tablename__ = "intake_manifest"

    manifest_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)   # local | drive
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")
    read_by: Mapped[str | None] = mapped_column(Text)

    declared_section_id: Mapped[str | None] = mapped_column(Text)
    declared_task_id: Mapped[str | None] = mapped_column(Text)
    declared_iteration: Mapped[str | None] = mapped_column(Text)
    declared_window_label: Mapped[str | None] = mapped_column(Text)

    file_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # The integration-health signal. A rise means account matching stopped working, and it shows
    # up here before it shows up as a wrong score.
    inferred_rate: Mapped[float | None] = mapped_column(Numeric)
    run_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("source_kind IN ('local','drive')", name="source_kind"),
        Index("ix_intake_manifest_source", "tenant_id", "source_ref", "read_at"),
    )


class File(Base, TenantMixin):
    """One file in one read, and what it turned out to be.

    `source_ref` is stable across reads — a Drive file id, or a path relative to the folder — which
    is what makes "the same document, edited" distinguishable from "a new document". A changed
    `text_hash` under one `source_ref` is a student who kept working: a NEW artifact superseding
    the old one under the same binding key, never an edit to the one already scored.

    The extracted text lives here rather than behind a `source_uri`. The batch job had a local
    filesystem and the review console does not, and a source that has moved or lost its permission
    would leave a reviewed artifact whose text nobody can read.
    """
    __tablename__ = "intake_file"

    file_id: Mapped[str] = mapped_column(Text, primary_key=True)
    manifest_id: Mapped[str] = mapped_column(
        ForeignKey("intake_manifest.manifest_id"), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str | None] = mapped_column(Text)
    modified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    owner_email: Mapped[str | None] = mapped_column(Text)
    editor_emails: Mapped[list | None] = mapped_column(JSONB)

    text: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    resolved_student_id: Mapped[str | None] = mapped_column(Text)
    resolution_basis: Mapped[str | None] = mapped_column(Text)   # owner_account|editor_account|name
    resolution_path: Mapped[str | None] = mapped_column(Text)    # looked_up | inferred
    match_score: Mapped[float | None] = mapped_column(Numeric)
    # The near-misses, for the console's stuck queue: who this might be, and why we could not tell.
    candidates: Mapped[list | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in FILE_STATUSES) + ")", name="status"),
        # Resolved means a person was named. Anything else must not carry one, or a half-matched
        # file quietly becomes somebody's paper.
        CheckConstraint("(status = 'resolved') = (resolved_student_id IS NOT NULL)",
                        name="resolved_names_a_student"),
        UniqueConstraint("manifest_id", "source_ref", name="uq_intake_file_source_ref"),
        Index("ix_intake_file_manifest", "manifest_id", "status"),
        Index("ix_intake_file_hash", "text_hash"),
        Index("ix_intake_file_student", "tenant_id", "resolved_student_id"),
    )
