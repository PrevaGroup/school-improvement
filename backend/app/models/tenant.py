"""Private / tenant tables (TARGET_SCHEMA §5, §4.2, §4.7).

Every row carries `tenant_id` + `visibility`. These tables get ENABLE + FORCE ROW
LEVEL SECURITY and the policies in migration 0001. Public/state data lives in
`fact_metric` too, as rows with tenant_id='public', visibility='public'.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TenantMixin:
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("dim_tenant.tenant_id"), nullable=False, server_default="public"
    )
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default="public")  # public|private|shared


# --------------------------------------------------------------------------- #
# Time grain (§4.2) — tenant-scoped: public standard periods + private cadences.
# --------------------------------------------------------------------------- #
class DimPeriod(TenantMixin, Base):
    __tablename__ = "dim_period"
    period_id: Mapped[str] = mapped_column(Text, primary_key=True)
    grain: Mapped[str | None] = mapped_column(Text)                 # annual|term|grading_period|month|biweekly|week|window
    school_year: Mapped[str | None] = mapped_column(Text)          # containing year (rollup/filter)
    label: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[Date | None] = mapped_column(Date)
    end_date: Mapped[Date | None] = mapped_column(Date)
    day_in_session_start: Mapped[int | None] = mapped_column(Integer)
    day_in_session_end: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int | None] = mapped_column(Integer)
    is_current: Mapped[bool | None] = mapped_column(Boolean)


# --------------------------------------------------------------------------- #
# The keystone fact (§5.1) — grain: school_id × period_id × metric × group.
# --------------------------------------------------------------------------- #
class FactMetric(TenantMixin, Base):
    __tablename__ = "fact_metric"
    school_id: Mapped[str] = mapped_column(ForeignKey("dim_school.school_id"), primary_key=True)
    period_id: Mapped[str] = mapped_column(ForeignKey("dim_period.period_id"), primary_key=True)
    metric_id: Mapped[str] = mapped_column(ForeignKey("dim_metric.metric_id"), primary_key=True)
    student_group_id: Mapped[str] = mapped_column(
        ForeignKey("dim_student_group.student_group_id"), primary_key=True
    )
    # measured (§5.4 missingness)
    value: Mapped[float | None] = mapped_column(Numeric)
    value_status: Mapped[str | None] = mapped_column(Text)   # reported|suppressed|no_students|not_applicable|not_collected|not_loaded|unknown
    n_size: Mapped[int | None] = mapped_column(Integer)
    is_suppressed: Mapped[bool | None] = mapped_column(Boolean)
    is_unmapped: Mapped[bool | None] = mapped_column(Boolean)
    instrument_id: Mapped[str | None] = mapped_column(Text)   # -> dim_instrument (§4.7)
    source_dataset: Mapped[str | None] = mapped_column(Text)  # lineage
    # benchmarks (computed)
    value_state: Mapped[float | None] = mapped_column(Numeric)
    value_district: Mapped[float | None] = mapped_column(Numeric)
    value_peer_median: Mapped[float | None] = mapped_column(Numeric)
    value_prior: Mapped[float | None] = mapped_column(Numeric)
    value_all_group: Mapped[float | None] = mapped_column(Numeric)
    target_value: Mapped[float | None] = mapped_column(Numeric)
    # derived (signed toward good via dim_metric.direction)
    change: Mapped[float | None] = mapped_column(Numeric)
    change_3yr_slope: Mapped[float | None] = mapped_column(Numeric)
    series_break: Mapped[bool | None] = mapped_column(Boolean)  # instrument changed vs prior period
    gap_vs_state: Mapped[float | None] = mapped_column(Numeric)
    gap_vs_peer: Mapped[float | None] = mapped_column(Numeric)
    gap_vs_all_students: Mapped[float | None] = mapped_column(Numeric)
    z_in_peer: Mapped[float | None] = mapped_column(Numeric)
    pctile_in_peer: Mapped[float | None] = mapped_column(Numeric)
    status_level: Mapped[str | None] = mapped_column(Text)
    change_level: Mapped[str | None] = mapped_column(Text)
    band: Mapped[str | None] = mapped_column(Text)             # 5x5 status×change color


# Moved out of core 2026-07-15: plan / plan_goal / plan_action -> etl/ca/sip/models.py.
# They are sip's tables, not shared schema. `TenantMixin` above stays here and sip imports
# it: tenant_id + visibility IS the trust boundary, so core defines it and modules apply
# it — a module must never invent its own. core's PRIVATE_TABLES still names these three
# by string to drive RLS policy generation, which is the same principle (the boundary is
# core's job) and is not an import, so the module rule holds.
