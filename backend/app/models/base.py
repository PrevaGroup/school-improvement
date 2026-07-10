from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Stable constraint/index names so Alembic autogenerate is deterministic.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Tables that carry tenant data and get ENABLE + FORCE ROW LEVEL SECURITY.
# Everything else is public reference (shared, read by everyone, no RLS).
PRIVATE_TABLES = ("fact_metric", "plan", "plan_goal", "plan_action")

# fact_metric additionally scopes WRITES to the tenant's own schools (cds_prefix).
SCHOOL_SCOPED_TABLES = ("fact_metric",)
