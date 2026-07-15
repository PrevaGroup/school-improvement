"""The tables the `likeschools` module owns — its contract with everything downstream.

Moved out of `core` (`app/models/reference.py`) 2026-07-15: these are this module's
tables, not shared schema, and while they sat in `core` every change to them was a
breaking change to the frozen contract. Nothing downstream imports these classes —
serving reads `mart_school_peer` with SQL — so this module can be rewritten freely as
long as the table shapes below hold. That is the whole point of the seam.

`Base` comes from `core`: one declarative registry means one Alembic history, which is
the deliberate trade in docs/MODULES.md (module-owned tables, single migration spine).

REGISTRATION — read before moving anything here:
    These classes only reach `Base.metadata` if something imports this module. Two places
    depend on that, and BOTH must import it:
      * migrations/env.py       -> autogenerate; if it can't see a table it emits DROP TABLE
      * migrations/versions/0001_initial_schema.py -> Base.metadata.create_all() on a
        fresh database, then GRANTs/RLS over the created tables
    backend/tests/test_schema_inventory.py fails if a table stops being registered.

All public / no-RLS: computed from the public federal/state universe, identical for every
tenant, so none of these carry tenant_id.

NB (deviation from the spec's DDL): keyed on `school_id` (the platform's NCES identity),
not `nces_id`, to match the deployed dim_school. See ../../likeschools/school-classification-spec.md.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, Boolean, Float, SmallInteger, Text, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


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
    """Precomputed k-nearest peer lists — the 'schools like you' artifact (spec §5.2).

    THE module's public contract: `serving` reads this table directly (SQL, no import),
    so its shape is what must stay stable across any rewrite of the matching engine.
    """
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
