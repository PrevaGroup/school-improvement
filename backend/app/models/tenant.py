"""Private / tenant tables (§10.2).

Every row carries `tenant_id` + `visibility`. These tables get ENABLE + FORCE ROW
LEVEL SECURITY and the policies defined in migration 0001. Public state data lives
here too, as rows with tenant_id='public', visibility='public'.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, Date, ForeignKey, ForeignKeyConstraint, Integer, Numeric, SmallInteger, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TenantMixin:
    # 'public' rows are world-readable; a district's rows carry its tenant_id.
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("dim_tenant.tenant_id"), nullable=False, server_default="public"
    )
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default="public")  # public|private|shared


class FactMetric(TenantMixin, Base):
    __tablename__ = "fact_metric"
    # grain
    school_cds: Mapped[str] = mapped_column(Text, primary_key=True)
    school_year: Mapped[str] = mapped_column(Text, primary_key=True)
    metric_id: Mapped[str] = mapped_column(ForeignKey("dim_metric.metric_id"), primary_key=True)
    student_group_id: Mapped[str] = mapped_column(
        ForeignKey("dim_student_group.student_group_id"), primary_key=True
    )
    # measured (see §5.1 / §5.4)
    value: Mapped[float | None] = mapped_column(Numeric)
    value_status: Mapped[str | None] = mapped_column(Text)  # reported|suppressed|no_students|not_applicable|not_collected|not_loaded|unknown
    n_size: Mapped[int | None] = mapped_column(Integer)
    is_suppressed: Mapped[bool | None] = mapped_column(Boolean)
    is_unmapped: Mapped[bool | None] = mapped_column(Boolean)
    instrument_id: Mapped[str | None] = mapped_column(Text)   # -> dim_instrument (§4.7)
    period: Mapped[str | None] = mapped_column(Text)
    # benchmarks / derived
    value_state: Mapped[float | None] = mapped_column(Numeric)
    value_district: Mapped[float | None] = mapped_column(Numeric)
    value_peer_median: Mapped[float | None] = mapped_column(Numeric)
    value_prior: Mapped[float | None] = mapped_column(Numeric)
    target_value: Mapped[float | None] = mapped_column(Numeric)
    change: Mapped[float | None] = mapped_column(Numeric)
    gap_vs_state: Mapped[float | None] = mapped_column(Numeric)
    gap_vs_peer: Mapped[float | None] = mapped_column(Numeric)
    gap_vs_all_students: Mapped[float | None] = mapped_column(Numeric)
    z_in_peer: Mapped[float | None] = mapped_column(Numeric)
    pctile_in_peer: Mapped[float | None] = mapped_column(Numeric)
    series_break: Mapped[bool | None] = mapped_column(Boolean)
    status_level: Mapped[str | None] = mapped_column(Text)
    change_level: Mapped[str | None] = mapped_column(Text)
    dashboard_color: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        ForeignKeyConstraint(
            ["school_cds", "school_year"],
            ["dim_school.school_cds", "dim_school.school_year"],
        ),
    )


class Plan(TenantMixin, Base):
    __tablename__ = "plan"
    plan_id: Mapped[str] = mapped_column(Text, primary_key=True)
    school_cds: Mapped[str | None] = mapped_column(Text)
    plan_year: Mapped[str | None] = mapped_column(Text)
    plan_type: Mapped[str | None] = mapped_column(Text)      # SPSA|LCAP|CSI|TSI|ATSI
    status: Mapped[str | None] = mapped_column(Text)
    adopted_date: Mapped[Date | None] = mapped_column(Date)
    total_budget: Mapped[float | None] = mapped_column(Numeric)
    funding_sources: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)


class PlanGoal(TenantMixin, Base):
    __tablename__ = "plan_goal"
    goal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plan.plan_id"))
    lcff_priority: Mapped[int | None] = mapped_column(SmallInteger)
    linked_metric_id: Mapped[str | None] = mapped_column(Text)   # -> dim_metric (may be a local metric)
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
    target_metric_id: Mapped[str | None] = mapped_column(Text)   # derived argmax(weight) — see schema §6
    target_group_id: Mapped[str | None] = mapped_column(Text)
    budgeted_amount: Mapped[float | None] = mapped_column(Numeric)
    funding_source_id: Mapped[str | None] = mapped_column(Text)
    fte: Mapped[float | None] = mapped_column(Numeric)
    role_type: Mapped[str | None] = mapped_column(Text)
    is_district_provided: Mapped[bool | None] = mapped_column(Boolean)
    owner: Mapped[str | None] = mapped_column(Text)
