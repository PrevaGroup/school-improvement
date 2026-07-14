"""Public / conformed reference tables — the shared 'yardsticks' (TARGET_SCHEMA §7.2).

No RLS: every tenant reads these. Written only by the migrator / ETL role.
Includes the tenancy registry (dim_tenant / tenant_scope / tenant_membership), which
must be readable so RLS policies can evaluate write scope.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, Boolean, Float, Integer, Numeric, SmallInteger, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


# --------------------------------------------------------------------------- #
# Tenancy registry (§7.1) — level-agnostic tenant, membership defines scope.
# --------------------------------------------------------------------------- #
class DimTenant(Base):
    __tablename__ = "dim_tenant"
    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)   # LEA id, or synthetic
    tenant_type: Mapped[str | None] = mapped_column(Text)            # state|district|coe|charter|cmo|consortium|private_school|public
    display_name: Mapped[str | None] = mapped_column(Text)
    jurisdiction: Mapped[str | None] = mapped_column(Text)           # 'CA', ...


class TenantScope(Base):
    """Which schools a tenant owns (write authority). Replaces a cds-prefix rule."""
    __tablename__ = "tenant_scope"
    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    school_id: Mapped[str] = mapped_column(Text, primary_key=True)


class TenantMembership(Base):
    """Nesting: a tenant's parent/consortium. Parent reads children's data."""
    __tablename__ = "tenant_membership"
    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)   # member
    parent_id: Mapped[str] = mapped_column(Text, primary_key=True)   # consortium/parent


# --------------------------------------------------------------------------- #
# Core dimensions
# --------------------------------------------------------------------------- #
class DimSchool(Base):
    """Current-snapshot school dimension.

    Identity keys on the **federal NCES** ids; state-native codes are attributes + a
    crosswalk (TARGET_SCHEMA §identity). `school_id` = 12-digit NCES school id (ncessch),
    `district_id` = 7-digit NCES LEAID. The CA CDS codes ride alongside as `state_*_id`.
    """
    __tablename__ = "dim_school"
    school_id: Mapped[str] = mapped_column(Text, primary_key=True)   # NCES school id (ncessch, 12-digit)
    district_id: Mapped[str | None] = mapped_column(Text)            # NCES LEAID (7-digit)
    state_school_id: Mapped[str | None] = mapped_column(Text)        # state-native school code (CA 14-digit CDS)
    state_district_id: Mapped[str | None] = mapped_column(Text)      # state-native district code (CA CDS district)
    school_year: Mapped[str | None] = mapped_column(Text)           # snapshot year (attribute, not key)
    school_name: Mapped[str | None] = mapped_column(Text)
    district_name: Mapped[str | None] = mapped_column(Text)
    county_name: Mapped[str | None] = mapped_column(Text)
    school_level: Mapped[str | None] = mapped_column(Text)          # ES|MS|HS|Other
    grade_low: Mapped[str | None] = mapped_column(Text)
    grade_high: Mapped[str | None] = mapped_column(Text)
    is_charter: Mapped[bool | None] = mapped_column(Boolean)
    is_title_i: Mapped[bool | None] = mapped_column(Boolean)
    is_dass: Mapped[bool | None] = mapped_column(Boolean)
    locale: Mapped[str | None] = mapped_column(Text)               # City|Suburb|Town|Rural
    enroll_total: Mapped[int | None] = mapped_column(Integer)
    pct_sed: Mapped[float | None] = mapped_column(Numeric)
    pct_el: Mapped[float | None] = mapped_column(Numeric)
    pct_swd: Mapped[float | None] = mapped_column(Numeric)
    latitude: Mapped[float | None] = mapped_column(Numeric)
    longitude: Mapped[float | None] = mapped_column(Numeric)
    peer_group_id: Mapped[str | None] = mapped_column(Text)         # -> dim_peer_group


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
# "Schools Like You" — input-matched demographic peer groups (public marts).
# See backend/likeschools/school-classification-spec.md. All public/no-RLS:
# computed from the public federal/state universe, identical for every tenant.
# NB (deviation from the spec's DDL): keyed on `school_id` (the platform's NCES
# identity), not `nces_id`, to match the deployed dim_school.
# --------------------------------------------------------------------------- #
class FeatMatchVector(Base):
    """The standardized demographic match vector per school (spec §5.2)."""
    __tablename__ = "feat_match_vector"
    school_id: Mapped[str] = mapped_column(Text, primary_key=True)
    school_year: Mapped[str] = mapped_column(Text, primary_key=True)
    level_bucket: Mapped[str | None] = mapped_column(Text)  # Primary|Middle|High|Combined-Other
    f_econ_disadv: Mapped[float | None] = mapped_column(Float)
    f_el: Mapped[float | None] = mapped_column(Float)
    f_swd: Mapped[float | None] = mapped_column(Float)
    f_enroll_log: Mapped[float | None] = mapped_column(Float)
    f_locale_city: Mapped[float | None] = mapped_column(Float)
    f_locale_suburb: Mapped[float | None] = mapped_column(Float)
    f_locale_town: Mapped[float | None] = mapped_column(Float)
    f_locale_rural: Mapped[float | None] = mapped_column(Float)
    n_imputed: Mapped[int] = mapped_column(SmallInteger, server_default="0")


class MartSchoolPeer(Base):
    """Precomputed k-nearest peer lists — the 'schools like you' artifact (spec §5.2)."""
    __tablename__ = "mart_school_peer"
    school_id: Mapped[str] = mapped_column(Text, primary_key=True)
    peer_school_id: Mapped[str] = mapped_column(Text, primary_key=True)
    school_year: Mapped[str] = mapped_column(Text, primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger)          # 1..k, nearest first
    distance: Mapped[float] = mapped_column(Float)           # Mahalanobis distance
    level_bucket: Mapped[str | None] = mapped_column(Text)
    low_confidence: Mapped[bool] = mapped_column(Boolean, server_default="false")


class ModelPartitionStats(Base):
    """Per-partition model provenance for reproducibility/audit (spec §5.2).

    `precision_mat` is the inverse covariance S^-1, stored row-major flattened;
    reshape to (len(feature_names), len(feature_names)).
    """
    __tablename__ = "model_partition_stats"
    school_year: Mapped[str] = mapped_column(Text, primary_key=True)
    level_bucket: Mapped[str] = mapped_column(Text, primary_key=True)
    feature_names: Mapped[list[str]] = mapped_column(ARRAY(Text))
    means: Mapped[list[float]] = mapped_column(ARRAY(Float))
    sds: Mapped[list[float]] = mapped_column(ARRAY(Float))
    shrinkage: Mapped[float | None] = mapped_column(Float)
    precision_mat: Mapped[list[float]] = mapped_column(ARRAY(Float))
    k: Mapped[int | None] = mapped_column(SmallInteger)
    built_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class DimDate(Base):
    __tablename__ = "dim_date"
    date_key: Mapped[str] = mapped_column(Text, primary_key=True)   # 'YYYY-MM-DD'
    school_year: Mapped[str | None] = mapped_column(Text)
    month: Mapped[int | None] = mapped_column(SmallInteger)
    iso_week: Mapped[int | None] = mapped_column(SmallInteger)
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger)
    is_weekend: Mapped[bool | None] = mapped_column(Boolean)


class DimStudentGroup(Base):
    __tablename__ = "dim_student_group"
    student_group_id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str | None] = mapped_column(Text)
    dimension: Mapped[str | None] = mapped_column(Text)            # total|race|gender|ses|program|eng_prof
    is_equity_focus: Mapped[bool | None] = mapped_column(Boolean)


class GroupCrosswalk(Base):
    """Source subgroup code -> conformed student_group_id (§4.6)."""
    __tablename__ = "group_crosswalk"
    source_system: Mapped[str] = mapped_column(Text, primary_key=True)  # 'cde_reportingcategory'|'caaspp'|'directory'
    source_code: Mapped[str] = mapped_column(Text, primary_key=True)    # 'RB','SE',...
    student_group_id: Mapped[str | None] = mapped_column(Text)


class DimMetric(Base):
    __tablename__ = "dim_metric"
    metric_id: Mapped[str] = mapped_column(Text, primary_key=True)
    domain: Mapped[str | None] = mapped_column(Text)               # attendance|behavior|academics|climate|engagement|finance|staffing
    display_name: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)                 # pct|rate|scale_score|dfs_points|usd|fte
    direction: Mapped[str | None] = mapped_column(Text)           # higher_better|lower_better|context
    grains: Mapped[str | None] = mapped_column(Text)              # legit cadences, e.g. 'annual,month'
    applies_to_levels: Mapped[str | None] = mapped_column(Text)
    applies_to_grades: Mapped[str | None] = mapped_column(Text)
    is_leading_indicator: Mapped[bool | None] = mapped_column(Boolean)
    data_origin: Mapped[str | None] = mapped_column(Text)         # state|local_sis|local_survey
    instrument_dependent: Mapped[bool | None] = mapped_column(Boolean)
    definition: Mapped[str | None] = mapped_column(Text)
    suppress_threshold: Mapped[int | None] = mapped_column(SmallInteger, server_default="11")


class DimInstrument(Base):
    __tablename__ = "dim_instrument"
    instrument_id: Mapped[str] = mapped_column(Text, primary_key=True)  # 'core_css','panorama_climate','caaspp_sb',...
    vendor: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    scale_type: Mapped[str | None] = mapped_column(Text)          # pct_favorable|likert_mean_1_5|scale_score|rate
    scale_min: Mapped[float | None] = mapped_column(Numeric)
    scale_max: Mapped[float | None] = mapped_column(Numeric)
    version: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class DimPeerGroup(Base):
    __tablename__ = "dim_peer_group"
    peer_group_id: Mapped[str] = mapped_column(Text, primary_key=True)
    method: Mapped[str | None] = mapped_column(Text)             # rule|kmeans
    school_level: Mapped[str | None] = mapped_column(Text)
    enroll_band: Mapped[str | None] = mapped_column(Text)
    sed_quartile: Mapped[int | None] = mapped_column(SmallInteger)
    locale_class: Mapped[str | None] = mapped_column(Text)
    n_schools: Mapped[int | None] = mapped_column(Integer)


class DimMetricRelationship(Base):
    """Leverage graph: a leading metric drives a lagging one (§4.5)."""
    __tablename__ = "dim_metric_relationship"
    leading_metric_id: Mapped[str] = mapped_column(Text, primary_key=True)
    lagging_metric_id: Mapped[str] = mapped_column(Text, primary_key=True)
    strength: Mapped[float | None] = mapped_column(Numeric)      # 0..1


class RefBenchmark(Base):
    """Authoritative state/county/district aggregate values (public)."""
    __tablename__ = "ref_benchmark"
    level: Mapped[str] = mapped_column(Text, primary_key=True)          # 'T'|'C'|'D'
    entity_id: Mapped[str] = mapped_column(Text, primary_key=True)      # '' state, else county/district id
    period_id: Mapped[str] = mapped_column(Text, primary_key=True)
    metric_id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_group_id: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[float | None] = mapped_column(Numeric)
    n_size: Mapped[int | None] = mapped_column(Integer)
