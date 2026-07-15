"""The tables the `sip` module owns — its contract with everything downstream.

Moved out of `core` (`app/models/reference.py` + `app/models/tenant.py`) 2026-07-15: these
are this module's tables, not shared schema, and while they sat in `core` every change to
them was a breaking change to the frozen contract. Nothing downstream imports these
classes — serving reads `plan_extraction` with SQL — so this module can be rewritten
freely as long as the table shapes below hold.

`Base` and `TenantMixin` come from `core`: one declarative registry means one Alembic
history, and `TenantMixin` is the trust boundary (tenant_id + visibility), which is
core's to define, not a module's to invent.

REGISTRATION — read before moving anything here:
    These classes only reach `Base.metadata` if something imports this module. Two places
    depend on that, and BOTH must import it:
      * migrations/env.py       -> autogenerate; if it can't see a table it emits DROP TABLE
      * migrations/versions/0001_initial_schema.py -> Base.metadata.create_all() on a
        fresh database, then GRANTs/RLS over the created tables
    backend/tests/test_schema_inventory.py fails if a table stops being registered.

Two tiers live here, deliberately:
  * `plan_extraction` — PUBLIC (SPSAs are published documents), no RLS, served without a
    tenant binding. The full extractor output as queryable JSONB.
  * `plan` / `plan_goal` / `plan_action` — PRIVATE, tenant-scoped, RLS-enforced. Note
    `core`'s `PRIVATE_TABLES` still names these three by string to drive RLS policy
    generation; that's the trust boundary staying core's job, and a string is not an
    import, so the boundary holds.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.tenant import TenantMixin


class PlanExtraction(Base):
    """The full extracted plan JSON (schema.ExtractedPlan) as a queryable JSONB blob.

    Public tier (SPSAs are published documents), so served without a tenant binding.
    This holds everything the extractor produced — provenance quotes, funding text,
    proposed metric links — that the minimal normalized plan_* tables drop. It is the
    serving source for the plan-content marts until §5.2 (bridges/provenance) is built.
    """
    __tablename__ = "plan_extraction"
    plan_id: Mapped[str] = mapped_column(Text, primary_key=True)
    school_id: Mapped[str | None] = mapped_column(Text)      # NCES; joins dim_school
    plan_year: Mapped[str | None] = mapped_column(Text)
    plan_type: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[str | None] = mapped_column(Text)
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)


# --------------------------------------------------------------------------- #
# Plan stubs (augment layer — kept minimal; expanded later).
# --------------------------------------------------------------------------- #
class Plan(TenantMixin, Base):
    __tablename__ = "plan"
    plan_id: Mapped[str] = mapped_column(Text, primary_key=True)
    school_id: Mapped[str | None] = mapped_column(Text)
    plan_year: Mapped[str | None] = mapped_column(Text)
    plan_type: Mapped[str | None] = mapped_column(Text)      # SPSA|LCAP|CSI|TSI|ATSI
    status: Mapped[str | None] = mapped_column(Text)
    adopted_date: Mapped[Date | None] = mapped_column(Date)
    total_budget: Mapped[float | None] = mapped_column(Numeric)
    source_url: Mapped[str | None] = mapped_column(Text)


class PlanGoal(TenantMixin, Base):
    __tablename__ = "plan_goal"
    goal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plan.plan_id"))
    lcff_priority: Mapped[int | None] = mapped_column(SmallInteger)
    linked_metric_id: Mapped[str | None] = mapped_column(Text)
    target_group_id: Mapped[str | None] = mapped_column(Text)
    baseline_value: Mapped[float | None] = mapped_column(Numeric)
    baseline_year: Mapped[str | None] = mapped_column(Text)
    target_value: Mapped[float | None] = mapped_column(Numeric)
    target_year: Mapped[str | None] = mapped_column(Text)
    prior_status: Mapped[str | None] = mapped_column(Text)
    narrative: Mapped[str | None] = mapped_column(Text)


class PlanAction(TenantMixin, Base):
    __tablename__ = "plan_action"
    action_id: Mapped[str] = mapped_column(Text, primary_key=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("plan_goal.goal_id"))
    strategy_text: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[str | None] = mapped_column(Text)
    target_metric_id: Mapped[str | None] = mapped_column(Text)
    target_group_id: Mapped[str | None] = mapped_column(Text)
    budgeted_amount: Mapped[float | None] = mapped_column(Numeric)
    funding_source_id: Mapped[str | None] = mapped_column(Text)
    fte: Mapped[float | None] = mapped_column(Numeric)
    role_type: Mapped[str | None] = mapped_column(Text)
    is_district_provided: Mapped[bool | None] = mapped_column(Boolean)
