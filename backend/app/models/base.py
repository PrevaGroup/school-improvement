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


# Private tenant tables: get ENABLE + FORCE ROW LEVEL SECURITY + tenant policies.
# Everything else is public/conformed reference (shared, read by everyone, no RLS).
PRIVATE_TABLES = ("fact_metric", "dim_period", "plan", "plan_goal", "plan_action")

# Of the private tables, these additionally scope WRITES to the tenant's own
# schools (via tenant_scope). They carry a school_id column.
SCHOOL_SCOPED_TABLES = ("fact_metric",)
