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
        # `resolved` must name a person; the three statuses meaning "this cannot become a paper"
        # must not. `empty` is deliberately in neither: a blank document we CAN attribute is a
        # non-attempt by a named student — a `not_scorable` artifact, which is a real outcome on
        # that student's record — while a blank document we cannot attribute names nobody.
        CheckConstraint("status <> 'resolved' OR resolved_student_id IS NOT NULL",
                        name="resolved_names_a_student"),
        CheckConstraint("status NOT IN ('unresolved','not_student_work','unreadable') "
                        "OR resolved_student_id IS NULL",
                        name="only_an_attributable_file_names_a_student"),
        UniqueConstraint("manifest_id", "source_ref", name="uq_intake_file_source_ref"),
        Index("ix_intake_file_manifest", "manifest_id", "status"),
        Index("ix_intake_file_hash", "text_hash"),
        Index("ix_intake_file_student", "tenant_id", "resolved_student_id"),
    )


class DriveConnection(Base, TenantMixin):
    """One person's authorisation to read one Google account's Drive.

    Per-teacher OAuth, not domain-wide delegation: one refresh token reaches one teacher's Drive,
    where a delegated service account would reach everyone's — including staff files that have
    nothing to do with this product. The plan makes domain-wide a district-scale decision, and
    blast radius is the reason it is not this one.

    TWO IDENTITIES, DELIBERATELY. The person signed into the console and the Google account whose
    Drive is read are not necessarily the same, and in the pilot they are not. Recording only one
    would make "whose Drive did this folder come from" unanswerable — the question asked when a
    paper turns out to be somebody else's, or when a person leaves and their access must go too.

    THIS ROW IS A CREDENTIAL. `refresh_token` is long-lived. It is never selected by a serving
    query and never returned by an endpoint; `drive_view` returns the email and the status. Cloud
    SQL encrypts at rest. That is the honest floor for a POC and it is not a secrets manager —
    written here so nobody later assumes hardening already happened. Migration 0029.
    """
    __tablename__ = "intake_drive_connection"

    connection_id: Mapped[str] = mapped_column(Text, primary_key=True)
    principal_sub: Mapped[str] = mapped_column(Text, nullable=False)   # who connected it
    principal_email: Mapped[str | None] = mapped_column(Text)
    google_email: Mapped[str] = mapped_column(Text, nullable=False)    # whose Drive it reaches

    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    # As Google RETURNED them, not as we asked. A user who unticked a scope grants less than was
    # requested, and the failure should say "you did not grant Docs" rather than surfacing a 403.
    granted_scopes: Mapped[str] = mapped_column(Text, nullable=False)

    connected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # An expired refresh token is the normal end of a connection on an External/Testing consent
    # screen — Google expires them after seven days. Recorded so the console can say "reconnect"
    # rather than failing a folder read with a stack trace.
    failed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    failure_detail: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("failed_at IS NULL OR failure_detail IS NOT NULL",
                        name="a_failure_says_what_failed"),
        Index("ix_intake_drive_connection_principal", "tenant_id", "principal_sub"),
    )
