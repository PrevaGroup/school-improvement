"""initial schema + row-level security

Creates the public reference tables and the private tenant tables, then turns on
ENABLE + FORCE ROW LEVEL SECURITY and the tenant policies on the private ones.

Runs as the migrator role, which OWNS the resulting tables. The app role (sip_app)
only gets the table-level DML grants issued here — and because it is a non-owner,
NOBYPASSRLS role, the policies actually apply to it.

Revision ID: 0001
Revises:
"""
from __future__ import annotations

from alembic import op

from app.config import settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = settings.app_db_user

REFERENCE_TABLES = ["dim_tenant", "dim_student_group", "dim_metric", "dim_school", "ref_benchmark"]
PRIVATE_TABLES = ["fact_metric", "plan", "plan_goal", "plan_action"]
SCHOOL_SCOPED = {"fact_metric"}


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Tables — created from the SQLAlchemy models so DDL and ORM never drift.
    from app.models import Base
    Base.metadata.create_all(bind=bind)

    # 2. The 'public' tenant owns all public/state rows.
    op.execute(
        "INSERT INTO dim_tenant (tenant_id, tenant_type, display_name, cds_prefix) "
        "VALUES ('public', 'public', 'Public / state data', '') "
        "ON CONFLICT (tenant_id) DO NOTHING"
    )

    # 3. Reference tables: no RLS, app reads them.
    for t in REFERENCE_TABLES:
        op.execute(f"GRANT SELECT ON {t} TO {APP_ROLE}")

    # 4. Private tables: ENABLE + FORCE RLS, tenant policies, app DML grants.
    for t in PRIVATE_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")

        # READ: public rows for everyone, private rows only for their tenant.
        # current_setting(..., true) returns NULL when unset -> matches nothing
        # private (fail-closed).
        op.execute(
            f"""
            CREATE POLICY p_read ON {t} FOR SELECT
            USING (
                visibility = 'public'
                OR tenant_id = current_setting('app.tenant', true)
            )
            """
        )

        # WRITE: only your own rows; fact_metric additionally only about your own
        # schools (COALESCE handles the 'public' tenant whose prefix is '' -> LIKE '%').
        if t in SCHOOL_SCOPED:
            write_check = (
                "tenant_id = current_setting('app.tenant', true) "
                "AND school_cds LIKE COALESCE("
                "  (SELECT cds_prefix FROM dim_tenant "
                "   WHERE tenant_id = current_setting('app.tenant', true)), ''"
                ") || '%'"
            )
        else:
            write_check = "tenant_id = current_setting('app.tenant', true)"

        op.execute(
            f"""
            CREATE POLICY p_write ON {t} FOR ALL
            USING (tenant_id = current_setting('app.tenant', true))
            WITH CHECK ({write_check})
            """
        )

        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {APP_ROLE}")


def downgrade() -> None:
    for t in PRIVATE_TABLES:
        op.execute(f"DROP POLICY IF EXISTS p_write ON {t}")
        op.execute(f"DROP POLICY IF EXISTS p_read ON {t}")

    from app.models import Base
    Base.metadata.drop_all(bind=op.get_bind())
