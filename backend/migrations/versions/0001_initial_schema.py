"""initial star schema + row-level security

Creates the public/conformed reference tables and the private tenant tables, then
turns on ENABLE + FORCE ROW LEVEL SECURITY and the tenant policies on the private
ones. Write scope is enforced via the tenant_scope membership table.

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

REFERENCE_TABLES = [
    "dim_tenant", "tenant_scope", "tenant_membership",
    "dim_school", "dim_date", "dim_student_group", "group_crosswalk",
    "dim_metric", "dim_instrument", "dim_peer_group", "dim_metric_relationship",
    "ref_benchmark",
]
PRIVATE_TABLES = ["fact_metric", "dim_period", "plan", "plan_goal", "plan_action"]
SCHOOL_SCOPED = {"fact_metric"}   # write-scoped to the tenant's own schools


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Tables — created from the SQLAlchemy models so DDL and ORM never drift.
    #
    # Bounded to THIS revision's baseline (the two lists above) rather than the whole
    # metadata. A bare create_all() creates every table the models currently declare,
    # including ones later revisions own — so it created plan_extraction, and then 0003's
    # op.create_table("plan_extraction") hit an existing table. That made `alembic upgrade
    # head` on an empty database fail at 0003, exactly the path sql/20_reset_database.sql
    # exists to exercise. Latent, because it only bites a from-scratch build.
    #
    # sip's models are imported for plan/plan_goal/plan_action, which ARE part of this
    # baseline (see PRIVATE_TABLES). Importing that module also registers plan_extraction,
    # which is precisely why the table list is explicit: 0003 owns that one, not 0001.
    from app.models import Base
    import etl.ca.sip.models  # noqa: F401  — registers plan / plan_goal / plan_action
    baseline = [Base.metadata.tables[t] for t in (*REFERENCE_TABLES, *PRIVATE_TABLES)]
    Base.metadata.create_all(bind=bind, tables=baseline)

    # 2. The 'public' tenant owns all public/state rows.
    op.execute(
        "INSERT INTO dim_tenant (tenant_id, tenant_type, display_name, jurisdiction) "
        "VALUES ('public', 'public', 'Public / state data', 'CA') "
        "ON CONFLICT (tenant_id) DO NOTHING"
    )

    # 3. Reference tables: no RLS; app reads them.
    for t in REFERENCE_TABLES:
        op.execute(f"GRANT SELECT ON {t} TO {APP_ROLE}")

    # 4. Private tables: ENABLE + FORCE RLS, tenant policies, app DML grants.
    for t in PRIVATE_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")

        # READ: public rows for everyone; private rows only for their tenant.
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

        # WRITE: only your own rows. School-scoped tables additionally require the
        # school to be in your tenant_scope — except the 'public' tenant, which is
        # the state-data loader and may write any school.
        if t in SCHOOL_SCOPED:
            write_check = (
                "tenant_id = current_setting('app.tenant', true) AND ("
                "  current_setting('app.tenant', true) = 'public'"
                "  OR EXISTS (SELECT 1 FROM tenant_scope ts"
                f"            WHERE ts.tenant_id = current_setting('app.tenant', true)"
                f"              AND ts.school_id = {t}.school_id)"
                ")"
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
