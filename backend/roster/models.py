"""The four tables the `roster` module owns — who is in which class, and who may see it.

Design: the SIP teacher-subsystem expansion plan §7 (identity, sections, the FERPA milestone) and
agentic-scoring-pipeline-design v0.06 §6.1 (the score record's enrollment context).

This module is an engine: it serves nothing. `intake` reads it to reconcile a folder against a
roster, `scoring` stamps enrollment context onto events, and `serving` reads it to answer "may this
person see this paper". Rows come from a Classroom / SIS sync; nothing here is authored by hand.

WHY THIS IS A MODULE AND NOT `core`: a district is already a SIP tenant, which is the precondition
that keeps `dim_tenant` and `tenant_scope` untouched. Section membership is a relation between a
person and a class — it belongs beside the roster, not in the star schema. That decision is what
makes the second authorisation layer purely additive: new tables, new policies, no migration
against a frozen contract.

THE SECOND AUTHORISATION LAYER. SIP answers two questions with two mechanisms: who are you
(`get_current_principal`), and what may you see (`get_current_tenant` -> RLS). Student writing needs
a third — WHICH of your students is this — and it is answered here. `section_staff` holds the edges;
`roster_visible_sections()` (migration 0009) resolves them in SQL so a policy can use it. A bug that
leaks one teacher's students to another teacher inside a district is not meaningfully less serious
than a cross-district leak, so it gets the same class of defence: the database, not the router.

REGISTRATION — these classes only reach `Base.metadata` if something imports this module:
    * migrations/env.py                          -> autogenerate; unseen table means DROP TABLE
    * backend/tests/test_schema_inventory.py     -> mirrors that import list
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (CheckConstraint, Date, ForeignKey, Index, Text, TIMESTAMP,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.tenant import TenantMixin

# Who may act on a section, and what that lets them do. Deliberately small: the MVP has no
# per-user roles beyond these, and inventing a permission system before there is a second
# consumer of it is how you end up maintaining one.
STAFF_ROLES: tuple[str, ...] = (
    "teacher",     # owns review and release for this section
    "co_teacher",  # same rights; who reviews is a declared rule, not a default (see CONTRACT.md)
    "coach",       # reads the class-level readings; never an individual paper
)

RELEASE_ROLES = frozenset({"teacher", "co_teacher"})


class Student(Base, TenantMixin):
    """A student, identified stably across sections and across years.

    Two identifiers, deliberately. `student_id` is ours and never changes — a growth interval is
    paired on window labels for the same student, so an id that turned over between years would
    silently end every longitudinal claim. `external_key_hash` is the salted hash of whatever the
    sync matched on (a Classroom account, an SIS id); it can change when a district re-keys, and
    the raw value is never stored — the same posture `usage_chat_daily` takes with the principal.

    `display_name` IS stored: a teacher reviewing a paper needs to know whose it is, and a
    pseudonymous review queue would be unusable. It is tenant-scoped private data and never leaves
    the district — the aggregation seam in §7 carries no student key of any kind.
    """
    __tablename__ = "roster_student"

    student_id: Mapped[str] = mapped_column(Text, primary_key=True)
    external_key_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    grade: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        Index("ix_roster_student_external", "tenant_id", "external_key_hash"),
    )


class Section(Base, TenantMixin):
    """One class, taught in one term. The unit that scopes almost everything.

    Section resolution does more work than it looks like: it scopes student matching to a roster of
    ~30 rather than a school, which is the single largest lever on identity accuracy; it determines
    which rubric version is in force, since a teacher edit applies to a section; and it determines
    who reviews. `school_id` links to the star's `dim_school` when the sync knows it — nullable,
    because a district roster does not always carry an NCES id.
    """
    __tablename__ = "roster_section"

    section_id: Mapped[str] = mapped_column(Text, primary_key=True)
    school_id: Mapped[str | None] = mapped_column(ForeignKey("dim_school.school_id"))
    external_key: Mapped[str | None] = mapped_column(Text)   # Classroom course id, SIS section id
    name: Mapped[str | None] = mapped_column(Text)
    term_label: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        Index("ix_roster_section_school", "tenant_id", "school_id"),
        UniqueConstraint("tenant_id", "external_key", name="uq_roster_section_external_key"),
    )


class Enrollment(Base, TenantMixin):
    """A student in a section, over a validity window.

    Dated rather than current-state, for two reasons that are really one. A student who transfers
    mid-term leaves an enrollment that ended, not an enrollment that never existed — collapsing
    that to a delete makes an already-scored paper look like it belongs to nobody. And roster
    overlap between two scoring windows is computed from these dates: movement is reported over the
    class as enrolled at each window, with the overlap disclosed rather than corrected, and this is
    where that number comes from.

    A student enrolled in more than one section is two rows. Which section a paper binds to is a
    declared rule, not a default — see CONTRACT.md.
    """
    __tablename__ = "roster_enrollment"

    enrollment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    section_id: Mapped[str] = mapped_column(
        ForeignKey("roster_section.section_id"), nullable=False)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("roster_student.student_id"), nullable=False)
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)   # null = still enrolled
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        Index("ix_roster_enrollment_section", "tenant_id", "section_id"),
        Index("ix_roster_enrollment_student", "tenant_id", "student_id"),
        UniqueConstraint("section_id", "student_id", "active_from",
                         name="uq_roster_enrollment_span"),
    )


class SectionStaff(Base, TenantMixin):
    """The authorisation edge: this principal may act on this section, in this role.

    Keyed on `principal_hash` — the salted hash of the verified subject, the same identifier the
    trace envelope uses. No email is stored; the join to a person exists only via the salt. That is
    not decoration: this table is the answer to "which of your students is this", so it is the one
    an attacker would most want to read, and it should be worth as little as possible when read.

    Dated like enrollment, so a teacher who leaves mid-year stops seeing the class without their
    review history being deleted.
    """
    __tablename__ = "roster_section_staff"

    section_staff_id: Mapped[str] = mapped_column(Text, primary_key=True)
    section_id: Mapped[str] = mapped_column(
        ForeignKey("roster_section.section_id"), nullable=False)
    principal_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default="now()")

    __table_args__ = (
        Index("ix_roster_section_staff_principal", "tenant_id", "principal_hash"),
        Index("ix_roster_section_staff_section", "tenant_id", "section_id"),
        UniqueConstraint("section_id", "principal_hash", "role", "active_from",
                         name="uq_roster_section_staff_span"),
        CheckConstraint(
            "role IN (" + ",".join(f"'{r}'" for r in STAFF_ROLES) + ")", name="role"),
    )
