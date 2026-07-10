"""Public / reference tables — the shared 'yardsticks' (§10.4).

No RLS: every tenant reads these. Written only by the migrator/ETL role.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, Numeric, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DimTenant(Base):
    __tablename__ = "dim_tenant"
    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)      # 'public','lbusd',...
    tenant_type: Mapped[str | None] = mapped_column(Text)              # public|district|coe|state|consortium
    display_name: Mapped[str | None] = mapped_column(Text)
    cds_prefix: Mapped[str | None] = mapped_column(Text)              # district CDS(7) a tenant may WRITE about
    jurisdiction: Mapped[str | None] = mapped_column(Text, server_default="CA")


class DimStudentGroup(Base):
    __tablename__ = "dim_student_group"
    student_group_id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str | None] = mapped_column(Text)
    dimension: Mapped[str | None] = mapped_column(Text)               # total|race|gender|program|ses|eng_prof
    is_equity_focus: Mapped[bool | None] = mapped_column(Boolean)


class DimMetric(Base):
    __tablename__ = "dim_metric"
    metric_id: Mapped[str] = mapped_column(Text, primary_key=True)
    domain: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(Text)              # higher_better|lower_better|context
    applies_to_levels: Mapped[str | None] = mapped_column(Text)
    applies_to_grades: Mapped[str | None] = mapped_column(Text)
    is_leading_indicator: Mapped[bool | None] = mapped_column(Boolean)
    cadence: Mapped[str | None] = mapped_column(Text)
    source_dataset: Mapped[str | None] = mapped_column(Text)
    data_origin: Mapped[str | None] = mapped_column(Text)            # state|local_sis|local_survey
    instrument_dependent: Mapped[bool | None] = mapped_column(Boolean)
    definition: Mapped[str | None] = mapped_column(Text)
    suppress_threshold: Mapped[int | None] = mapped_column(SmallInteger, server_default="11")


class DimSchool(Base):
    __tablename__ = "dim_school"
    school_cds: Mapped[str] = mapped_column(Text, primary_key=True)   # 14-digit CDS
    school_year: Mapped[str] = mapped_column(Text, primary_key=True)  # '2023-24'
    school_name: Mapped[str | None] = mapped_column(Text)
    district_cds: Mapped[str | None] = mapped_column(Text)
    district_name: Mapped[str | None] = mapped_column(Text)
    county_name: Mapped[str | None] = mapped_column(Text)
    school_level: Mapped[str | None] = mapped_column(Text)
    grade_low: Mapped[str | None] = mapped_column(Text)
    grade_high: Mapped[str | None] = mapped_column(Text)
    is_charter: Mapped[bool | None] = mapped_column(Boolean)
    enroll_total: Mapped[int | None] = mapped_column(Integer)
    peer_group_id: Mapped[str | None] = mapped_column(Text)


class RefBenchmark(Base):
    """State/county/district aggregate values (CDE's T/C/D rows). Public."""
    __tablename__ = "ref_benchmark"
    level: Mapped[str] = mapped_column(Text, primary_key=True)          # 'T'|'C'|'D'
    entity_cds: Mapped[str] = mapped_column(Text, primary_key=True)     # '' for state, else county/district cds
    school_year: Mapped[str] = mapped_column(Text, primary_key=True)
    metric_id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_group_id: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[float | None] = mapped_column(Numeric)
    n_size: Mapped[int | None] = mapped_column(Integer)
