"""The two tables the `pooling` module owns — the only place that crosses the district threshold.

Design: the SIP teacher-subsystem expansion plan §7 ("Crossing the district threshold") and the LDC
PM console user design §2.1 / §7.

This module ships nearly empty, deliberately. What is here is the seam — the module boundary, the
consent gate, and the shape of the tenant-neutral tables. What is NOT here is the job that fills
them, because the suppression rule enforces its own timing: with a minimum district count, nothing
can be emitted until enough districts have consented, so the job cannot ship early by accident.

WHY A MODULE AT ALL, THIS EARLY. Because the property being protected is "there is exactly one
place cross-tenant code exists", and a property with zero exceptions is only cheap to maintain if it
starts with zero. `tests/test_module_boundaries.py` already walks every import; the assertion that
nothing else iterates tenants belongs beside it while the answer is trivially true.

THE THREE RULES, IN ORDER OF HOW EASILY THEY ARE LOST:

1. **Loop, don't join.** The job iterates districts, setting the tenant for each and accumulating in
   application memory. It never issues one query across tenant rows. This is not style: SIP forbids
   cross-tenant joins to keep the option of peeling a tenant into its own database, and a loop
   survives that peel — becoming a loop over databases — while a join does not. Writing it as a
   join would silently spend an option the platform is deliberately holding.

2. **Consent gates entry to the frame, not the output.** A district appears in the loop only while a
   current consent row permits it. Filtering afterwards would mean the aggregate was computed over
   data the district had not agreed to share, and then discarded — which is not the same thing.

3. **Nothing flows back.** No pooled figure re-enters a district's scoring path, anchored level, or
   any context assembled for a scorer. Pooled cross-district results are a comparison group, and a
   comparison group reaching the scorer is norm-referencing — the cohort-invariance failure the
   whole architecture exists to prevent, arriving at national scale through a side channel.

REGISTRATION — these classes only reach `Base.metadata` if something imports this module:
    * migrations/env.py                          -> autogenerate; unseen table means DROP TABLE
    * backend/tests/test_schema_inventory.py     -> mirrors that import list
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, Index, Text, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# What a district may agree to, separately. A district agreeing that module evidence may reach the
# publisher has not thereby agreed that its teachers' acceptance behaviour may — and conflating the
# two is how the override stream, the calibration asset the measurement design depends on, gets
# poisoned by teachers who reasonably conclude they are being monitored.
CONSENT_SCOPES: tuple[str, ...] = ("module_evidence", "teacher_instrumentation")

# Identifiers that must never appear on a tenant-neutral table. Asserted by the tests rather than
# left to review: the wall is a property of the data, because an interface-level rule is one
# someone can be persuaded to relax in a sprint planning meeting.
FORBIDDEN_KEYS: tuple[str, ...] = (
    "student_id", "teacher_id", "principal_hash", "artifact_id", "paper_id",
    "event_id", "section_id", "tenant_id", "school_id",
)


class AggregationConsent(Base):
    """A district's written agreement that aggregated results may reach the module publisher.

    Deliberately NOT tenant-scoped in the RLS sense — it is the gate on the crossing, read by the
    producer running as its own principal, so scoping it to the tenant being read would be circular.
    `district_tenant_id` is a plain column naming the district rather than a policy-bearing one.

    `effective_from` / `effective_to` exist because a figure computed under an earlier participation
    set is a different figure. Revocation propagates backward: withdrawing consent removes that
    district's contribution from existing aggregates by triggering recomputation, not just from the
    next run — forward-only revocation is cosmetic.

    The system holds the flag, not the agreement. A signed contract is not a fact any table holds,
    which is why `instrument_ref` points at where the real one lives.
    """
    __tablename__ = "pooling_aggregation_consent"

    consent_id: Mapped[str] = mapped_column(Text, primary_key=True)
    district_tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    instrument_ref: Mapped[str | None] = mapped_column(Text)   # where the signed agreement lives
    granted_by: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        UniqueConstraint("district_tenant_id", "scope", "effective_from", name="uq_pooling_consent_span"),
        CheckConstraint(
            "scope IN (" + ",".join(f"'{s}'" for s in CONSENT_SCOPES) + ")", name="scope"),
        Index("ix_pooling_consent_district", "district_tenant_id", "scope"),
    )


class AggregateRun(Base):
    """One execution of the producer: what it read, under which consent set, and what it emitted.

    The audit row. "Why does this number exist and who agreed to it" has to be answerable later,
    from the record — so the run stamps the consent snapshot it ran under, the suppression
    parameters applied, and the CONTRIBUTING DISTRICT COUNT rather than their identities.

    A count and not a list: the count is what a reader needs to judge whether a figure is thin, and
    the list is the thing that would let a determined reader difference two runs into an identity.
    """
    __tablename__ = "pooling_aggregate_run"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    definition_key: Mapped[str] = mapped_column(Text, nullable=False)  # which approved aggregate
    definition_version: Mapped[int] = mapped_column(nullable=False)
    frame_version: Mapped[str | None] = mapped_column(Text)
    configuration_version: Mapped[str | None] = mapped_column(Text)
    window_label: Mapped[str | None] = mapped_column(Text)

    consent_snapshot: Mapped[dict | None] = mapped_column(JSONB)   # consent ids in force at run time
    suppression_params: Mapped[dict | None] = mapped_column(JSONB)  # the k values applied

    district_count: Mapped[int | None] = mapped_column()
    cells_emitted: Mapped[int | None] = mapped_column()
    cells_suppressed: Mapped[int | None] = mapped_column()

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    stale_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index("ix_pooling_run_definition", "definition_key", "window_label"),
        CheckConstraint("status IN ('running','succeeded','failed','superseded')",
                        name="status"),
    )
