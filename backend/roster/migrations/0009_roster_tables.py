"""roster tables — sections, enrolments, and the section-scoped authorisation edge

Four tables plus `roster_visible_sections()`, the SQL function that resolves "which sections may
this principal act on". The function is here rather than in Python because it is what RLS policies
will call: a policy cannot invoke application code, and the whole argument for the second
authorisation layer is that it lives where an application bug cannot route around it.

RLS is NOT enabled on the scoring tables in this migration. That flip is a deliberate `core` move
made when the subsystem first holds real student writing (CLAUDE.md: never fold a core change into
a feature change). What this migration provides is the resolver those policies will use, so that
enabling them later is a policy statement rather than a redesign.

Revision ID: 0009
Revises: 0008
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_ROLES = ("teacher", "co_teacher", "coach")


def _tenancy() -> list[sa.Column]:
    return [
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    op.create_table(
        "roster_student",
        sa.Column("student_id", sa.Text(), primary_key=True),
        sa.Column("external_key_hash", sa.Text()),
        sa.Column("display_name", sa.Text()),
        sa.Column("grade", sa.Text()),
        *_tenancy(),
    )
    op.create_index("ix_roster_student_external", "roster_student",
                    ["tenant_id", "external_key_hash"])

    op.create_table(
        "roster_section",
        sa.Column("section_id", sa.Text(), primary_key=True),
        sa.Column("school_id", sa.Text(), sa.ForeignKey("dim_school.school_id")),
        sa.Column("external_key", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column("term_label", sa.Text()),
        sa.Column("subject", sa.Text()),
        sa.Column("synced_at", sa.TIMESTAMP(timezone=True)),
        *_tenancy(),
        sa.UniqueConstraint("tenant_id", "external_key", name="uq_roster_section_external_key"),
    )
    op.create_index("ix_roster_section_school", "roster_section", ["tenant_id", "school_id"])

    op.create_table(
        "roster_enrollment",
        sa.Column("enrollment_id", sa.Text(), primary_key=True),
        sa.Column("section_id", sa.Text(),
                  sa.ForeignKey("roster_section.section_id"), nullable=False),
        sa.Column("student_id", sa.Text(),
                  sa.ForeignKey("roster_student.student_id"), nullable=False),
        sa.Column("active_from", sa.Date()),
        sa.Column("active_to", sa.Date()),
        *_tenancy(),
        sa.UniqueConstraint("section_id", "student_id", "active_from",
                            name="uq_roster_enrollment_span"),
    )
    op.create_index("ix_roster_enrollment_section", "roster_enrollment",
                    ["tenant_id", "section_id"])
    op.create_index("ix_roster_enrollment_student", "roster_enrollment",
                    ["tenant_id", "student_id"])

    op.create_table(
        "roster_section_staff",
        sa.Column("section_staff_id", sa.Text(), primary_key=True),
        sa.Column("section_id", sa.Text(),
                  sa.ForeignKey("roster_section.section_id"), nullable=False),
        sa.Column("principal_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("active_from", sa.Date()),
        sa.Column("active_to", sa.Date()),
        *_tenancy(),
        sa.UniqueConstraint("section_id", "principal_hash", "role", "active_from",
                            name="uq_roster_section_staff_span"),
        sa.CheckConstraint("role IN (" + ",".join(f"'{r}'" for r in _ROLES) + ")",
                           name="role"),
    )
    op.create_index("ix_roster_section_staff_principal", "roster_section_staff",
                    ["tenant_id", "principal_hash"])
    op.create_index("ix_roster_section_staff_section", "roster_section_staff",
                    ["tenant_id", "section_id"])

    # ----------------------------------------------------------------------- #
    # The resolver.
    #
    # Reads `app.principal_hash`, set with SET LOCAL beside `app.tenant` — the client never sends
    # it, the same rule the tenant already follows. STABLE so the planner can hoist it out of a
    # per-row loop; SECURITY INVOKER so it cannot be used to see past a policy that would otherwise
    # apply to the caller.
    #
    # An unset principal resolves to no sections. That is the fail-closed direction: a code path
    # that forgot to say who it is sees nothing, rather than everything.
    # ----------------------------------------------------------------------- #
    op.execute("""
    CREATE FUNCTION roster_visible_sections(required_role text DEFAULT NULL)
    RETURNS TABLE (section_id text)
    LANGUAGE sql STABLE AS $$
        SELECT s.section_id
          FROM roster_section_staff s
         WHERE s.principal_hash = nullif(current_setting('app.principal_hash', true), '')
           AND (s.active_from IS NULL OR s.active_from <= current_date)
           AND (s.active_to   IS NULL OR s.active_to   >= current_date)
           AND (required_role IS NULL OR s.role = required_role)
    $$;

    COMMENT ON FUNCTION roster_visible_sections(text) IS
      'Sections the current principal may act on, optionally filtered to one role. Reads '
      'app.principal_hash (SET LOCAL, never client-supplied). Unset principal returns no rows: '
      'fail closed. Intended as the predicate for RLS policies on the scoring tables, which are '
      'enabled separately and deliberately.';
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS roster_visible_sections(text);")
    op.drop_table("roster_section_staff")
    op.drop_table("roster_enrollment")
    op.drop_table("roster_section")
    op.drop_table("roster_student")
