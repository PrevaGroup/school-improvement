"""The three tables the `measurement` module owns — which observations an estimate was fitted on.

Design: the SIP teacher-subsystem expansion plan §6 (three sets, not two) and §7 (deletion has a
psychometric consequence), and MFRM_Formative_Value_Requirements V8.27 §6.2.

An **engine**, like `likeschools`: it serves nothing and owns no endpoints. `serving` reads its
tables with SQL. The estimator itself — fits, facet estimates, fit statistics, bias interactions —
arrives with Phase 6, when there is something to fit. What lands here first is the thing that is
expensive to retrofit and cheap now: a record of exactly which observations any future estimate was
computed over.

THREE SETS, NOT TWO. The record is every score event ever written. The frame is the observations
legitimate enough to carry a measure against anchored parameters. The calibration is the subset that
actually moves item, rater and threshold estimates. `score_event.enters_calibration` stamps the
third at write time; this module defines and resolves the second, and keeps the definition versioned
so an estimate can be reproduced rather than merely repeated.

WHY THIS IS PHASE 0 AND NOT PHASE 6. Reproducibility is the reason, not deletion. An estimate
published in December and recomputed in March must be attributable to a definition, or the two
numbers are incomparable and nobody can say why they differ. Deletion propagation then comes
almost free: a removed student writes a tombstone, every frame that admitted them is marked stale,
and re-estimation is a job rather than an incident. Building it the other way round — deletion
first — produces a mechanism nobody exercises until a district asks, which is the worst moment to
discover it does not work.

REGISTRATION — these classes only reach `Base.metadata` if something imports this module:
    * migrations/env.py                          -> autogenerate; unseen table means DROP TABLE
    * backend/tests/test_schema_inventory.py     -> mirrors that import list
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (CheckConstraint, ForeignKey, Index, Text, TIMESTAMP, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.tenant import TenantMixin

# A frame is drafted, then activated, then eventually superseded by a later version. `stale` is the
# state a tombstone puts it in: the definition still stands, but the observations it resolved to no
# longer exist, so anything fitted on it needs recomputing before it is quoted again.
FRAME_STATUSES: tuple[str, ...] = ("draft", "active", "stale", "superseded")

# The keys an admission definition may carry. Documented here rather than enforced as columns
# because the admission policy is still an open decision — escalated scores, set-level overrides
# and formative mini-task scores each have a conservative default to argue against, and freezing
# them into a schema would settle by accident what should be settled on purpose.
#
# Drafts are the one part already settled: retained in the frame, excluded from the calibration.
DEFINITION_KEYS: tuple[str, ...] = (
    "windows",              # ["fall 2026", "spring 2027"] — declared labels, never elapsed time
    "node_ids",             # which items are in scope
    "scorer_types",         # ai | teacher | expert
    "iterations",           # which iterations are admitted at all
    "measurement_occasions_only",   # bool — the registry's declared occasion per task
    "include_escalated",    # a different administration of the same rater
    "include_set_overrides",        # one judgment covering many artifacts
    "include_formative",    # mini-task scores: thin linking coverage argues for admitting
    "min_scrutiny_passes",
    "max_scrutiny_passes",
)


class EstimationFrame(Base, TenantMixin):
    """A versioned, reproducible definition of which observations an estimate is fitted over.

    Immutable once active. Changing what a frame admits produces a NEW version rather than an edit,
    because an estimate quoted last month has to remain attributable to the definition that
    produced it — a definition that can change under a published number is not a definition.

    `definition_hash` is what makes reproducibility checkable rather than asserted: the same
    definition and the same score events must resolve to the same membership, and a hash mismatch
    says which of the two moved.
    """
    __tablename__ = "estimation_frame"

    frame_id: Mapped[str] = mapped_column(Text, primary_key=True)
    frame_key: Mapped[str] = mapped_column(Text, nullable=False)   # stable across versions
    version: Mapped[int] = mapped_column(nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    definition_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    description: Mapped[str | None] = mapped_column(Text)

    # Which frame this one replaced. A chain, not an edit history.
    supersedes_frame_id: Mapped[str | None] = mapped_column(
        ForeignKey("estimation_frame.frame_id"))

    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    member_count: Mapped[int | None] = mapped_column()
    stale_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        UniqueConstraint("tenant_id", "frame_key", "version", name="version"),
        CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in FRAME_STATUSES) + ")", name="status"),
        Index("ix_estimation_frame_key", "tenant_id", "frame_key", "status"),
    )


class EstimationFrameMember(Base, TenantMixin):
    """The resolved membership — which score events this frame version actually admitted.

    Materialised rather than computed at read time, and that is the whole point of the module. A
    definition plus a live table is not reproducible: score events keep arriving, so re-running the
    query next week answers a different question. The snapshot is what a published estimate refers
    to; the definition is what lets you rebuild the snapshot and prove it is the same one.

    `enters_calibration` is copied from the event at resolve time. It lives on the event as the
    authoritative stamp, and here so the calibration subset is a query against one table rather
    than a join whose meaning depends on when it ran.
    """
    __tablename__ = "estimation_frame_member"

    frame_id: Mapped[str] = mapped_column(
        ForeignKey("estimation_frame.frame_id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("score_event.event_id"), primary_key=True)
    enters_calibration: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    __table_args__ = (
        Index("ix_estimation_frame_member_calibration",
              "frame_id", "enters_calibration"),
        Index("ix_estimation_frame_member_event", "event_id"),
    )


class DeletionTombstone(Base, TenantMixin):
    """A subject that has been removed, and what that invalidates.

    Deletion has a psychometric consequence the rest of the system does not: removing a student
    removes their observations from the frame an anchored calibration was fitted on, which can
    change the estimates every other student's figures were corrected by. A row disappearing
    silently is therefore not deletion done well — it is deletion done invisibly.

    The tombstone records that the subject is gone without retaining what was deleted, and marks
    every frame that admitted them `stale`. Re-estimation is then a job someone runs, rather than
    an incident someone discovers.
    """
    __tablename__ = "measurement_deletion_tombstone"

    tombstone_id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)   # student | section | artifact
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(Text)
    frames_marked_stale: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        Index("ix_measurement_tombstone_subject", "tenant_id", "subject_type", "subject_id"),
        CheckConstraint("subject_type IN ('student','section','artifact')", name="subject_type"),
    )
