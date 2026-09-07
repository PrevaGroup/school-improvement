"""The one table `delivery` owns — what happened after a teacher said yes.

Design: the expansion plan §7 ("a hand-back can fail because the teacher no longer has edit access
to a student's document, and that is recorded as not sent rather than silently as delivered.
Released and delivered are different facts") and §11 Phase 4 ("delivery back to the document,
recorded, with failures recorded as failures").

WHY DELIVERY IS NOT A STATE OF THE ARTIFACT. `artifact.state` ends at `released` and stays there.
A teacher's decision and what happened to the network afterwards are different kinds of fact: the
first is a judgment that cannot fail, the second is an I/O operation that fails routinely. Folding
a delivery failure into the state machine would let a transient network error move a paper out of
`released`, which would then need a transition back — and a state machine with a retry loop in it
has stopped being a record of decisions.

WHY THE RECORD SURVIVES SUPERSESSION. The plan is specific about this and it is not bookkeeping:
"the student received feedback on the superseded draft — that is what makes the next draft
feedback-mediated, and it is the only thing that lets a growth claim over that pair be qualified
honestly." A student who was told what to fix and then fixed it did not improve the way a student
who was told nothing did. Erasing the delivery record to tidy a superseded artifact destroys the
only evidence of which case you are looking at.

REGISTRATION — this class only reaches `Base.metadata` if something imports this module:
    * migrations/env.py                          -> autogenerate; unseen table means DROP TABLE
    * backend/tests/test_schema_inventory.py     -> mirrors that import list
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.tenant import TenantMixin

# `queued` is the console prototype's "approved, waiting to go out": a teacher who hands back at
# the end of the lesson has approved something that has deliberately not gone yet, which is not a
# failure and must not read as one.
DELIVERY_STATUSES: tuple[str, ...] = ("queued", "sent", "failed", "not_sent")

# Two real ones from the plan — comments on the student's own document, or Classroom — neither of
# which requires the student to sign in, which is what keeps a consent and minor-account surface
# out of the pilot. `file` is the prototype's, and it is real delivery to a real place.
CHANNELS: tuple[str, ...] = ("file", "google_docs_comment", "classroom", "none")


class Delivery(Base, TenantMixin):
    """One attempt to hand one message back. Append-only, enforced by trigger.

    A retry is a NEW row pointing at the one it follows. Editing an attempt would erase the fact
    that a delivery once failed, which is exactly the fact a teacher needs when a student says they
    never got anything: "we tried at 09:41, the document had been moved, we tried again at 14:02
    and it went."
    """
    __tablename__ = "artifact_delivery"

    delivery_id: Mapped[str] = mapped_column(Text, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifact.artifact_id"), nullable=False)
    # WHICH message went. A composition is superseded when a teacher edits it, so a delivery that
    # named only the artifact could not answer "what did the student actually read".
    composition_id: Mapped[str] = mapped_column(Text, nullable=False)

    channel: Mapped[str] = mapped_column(Text, nullable=False)
    target_ref: Mapped[str | None] = mapped_column(Text)   # path, Drive file id, comment id
    status: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)       # the failure, in its own words
    # If a message is edited after delivery, this is what proves the student read the earlier one.
    message_hash: Mapped[str | None] = mapped_column(Text)

    attempted_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")
    delivered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    attempted_by: Mapped[str | None] = mapped_column(Text)
    supersedes_delivery_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_delivery.delivery_id"))

    __table_args__ = (
        CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in DELIVERY_STATUSES) + ")", name="status"),
        CheckConstraint(
            "channel IN (" + ",".join(f"'{c}'" for c in CHANNELS) + ")", name="channel"),
        # Sent means it arrived somewhere and we know when. A `sent` row with no timestamp and no
        # target is a claim with nothing behind it.
        CheckConstraint(
            "status <> 'sent' OR (delivered_at IS NOT NULL AND target_ref IS NOT NULL)",
            name="sent_says_where_and_when"),
        # The row somebody reads at 8am with a student standing in front of them.
        CheckConstraint("status <> 'failed' OR detail IS NOT NULL",
                        name="a_failure_says_what_failed"),
        Index("ix_artifact_delivery_artifact", "artifact_id", "attempted_at"),
        Index("ix_artifact_delivery_queue", "tenant_id", "status", "attempted_at"),
    )
