"""student work is readable only by the people who teach it

Until now the writing tables carried `tenant_id` and nothing enforced it. They were not in
`PRIVATE_TABLES`, and every student-work route opened its session through `get_db_public`, so any
signed-in user of either product could read every paper in every district. That was tolerable only
because the subsystem holds corpus and fixture papers; it is the Phase 0 seam the expansion plan
called for — "section-scoped relations in the roster tables and in the RLS policies" — and it has
to exist before the first real paper, not be added after one.

## Two keys, not one

SIP's private tables check one thing: `tenant_id = app.tenant`. Student work checks that AND the
section, resolved from `app.principal_hash` through `roster_visible_sections()` (migration 0009,
written for exactly this and never called until now). A leak between two teachers in one district
deserves the same defence as a leak between districts, and the only defence that survives a bug in
a query is the database's.

Children inherit from their parent rather than repeating the section test: a score event is visible
when its artifact is, a file when its manifest is. The subquery against the parent is itself
filtered by the parent's policy, so there is one definition of "your class" and every table defers
to it.

## Per command, and no DELETE anywhere

Each table gets a policy only for what the API actually does to it. A command with no policy is
refused once RLS is on, so the API role cannot delete student work at all, cannot write the roster
it is authorised by, and cannot read the four tables it never touches — Drive connections (they
name OAuth secrets), estimation frames and their members, and deletion tombstones.

## ENABLE, deliberately not FORCE

SIP's private tables use FORCE, so even the owner is subject to policy and the ETL sets
`app.tenant` before it writes. Here the owner is `sip_migrator`, and it is what the batch jobs run
as — scoring runs, the corpus loader, the fit — across every tenant including `corpus`. Forcing the
policy on them would make every batch job need a principal it does not have. The boundary this
migration draws is the API: `sip_app`, the role every request runs as, is bound. Moving the batch
jobs onto a role of their own is the schema split that follows this, not a reason to delay it.

## What it does not change

The fixture papers stay in tenant `public`. Moving them is blocked by the append-only triggers,
which are right to block it, and nothing reads them now without a staff row naming that section.
`python -m roster.grant_staff` is how a person gets one.

Revision ID: 0041
Revises: 0040
"""
from __future__ import annotations

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

APP_ROLE = "sip_app"

_TENANT = "tenant_id = nullif(current_setting('app.tenant', true), '')"


def _in_my_sections(column: str) -> str:
    return f"{column} IN (SELECT section_id FROM roster_visible_sections())"


def _visible_through(column: str, parent: str) -> str:
    return f"{column} IN (SELECT {column} FROM {parent})"


# table -> (predicate, commands the API performs). Read by the tests, so a table added to a
# writing module without a line here fails CI rather than shipping readable by everyone.
POLICIES: dict[str, tuple[str, tuple[str, ...]]] = {
    # The authorisation edge itself: a person sees their own staff rows and nobody else's.
    "roster_section_staff": (
        "principal_hash = nullif(current_setting('app.principal_hash', true), '')",
        ("SELECT",)),
    "roster_section":    (f"{_TENANT} AND {_in_my_sections('section_id')}", ("SELECT",)),
    "roster_enrollment": (f"{_TENANT} AND {_in_my_sections('section_id')}", ("SELECT",)),
    "roster_student":    (f"{_TENANT} AND {_visible_through('student_id', 'roster_enrollment')}",
                          ("SELECT",)),

    "artifact": (f"{_TENANT} AND {_in_my_sections('section_id')}", ("SELECT", "UPDATE")),
    "score_event": (f"{_TENANT} AND {_visible_through('artifact_id', 'artifact')}",
                    ("SELECT", "INSERT")),
    # INSERT because the transition trigger writes it as the invoking role.
    "artifact_state_transition": (f"{_TENANT} AND {_visible_through('artifact_id', 'artifact')}",
                                  ("SELECT", "INSERT")),
    "artifact_composition": (f"{_TENANT} AND {_visible_through('artifact_id', 'artifact')}",
                             ("SELECT", "INSERT")),
    "artifact_delivery": (f"{_TENANT} AND {_visible_through('artifact_id', 'artifact')}",
                          ("SELECT",)),

    "intake_manifest": (f"{_TENANT} AND {_in_my_sections('declared_section_id')}",
                        ("SELECT", "UPDATE")),
    "intake_file": (f"{_TENANT} AND {_visible_through('manifest_id', 'intake_manifest')}",
                    ("SELECT", "UPDATE")),

    "measurement_fit_run": (f"{_TENANT} AND {_in_my_sections('section_id')}", ("SELECT",)),
    "measurement_fit_element": (f"{_TENANT} AND {_visible_through('run_id', 'measurement_fit_run')}",
                                ("SELECT",)),
}

# RLS on, no policy: the API role reads and writes none of it. Batch jobs, as owner, are unaffected.
DENY_ALL: tuple[str, ...] = (
    "intake_drive_connection",
    "estimation_frame",
    "estimation_frame_member",
    "measurement_deletion_tombstone",
)


def _policy_name(command: str) -> str:
    return f"p_classes_{command.lower()}"


def upgrade() -> None:
    for table, (predicate, commands) in POLICIES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        for command in commands:
            if command == "INSERT":
                clause = f"WITH CHECK ({predicate})"
            elif command == "UPDATE":
                # Same test before and after: a row cannot be moved out of the caller's classes.
                clause = f"USING ({predicate}) WITH CHECK ({predicate})"
            else:
                clause = f"USING ({predicate})"
            op.execute(f"CREATE POLICY {_policy_name(command)} ON {table} "
                       f"FOR {command} TO {APP_ROLE} {clause}")

    for table in DENY_ALL:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in DENY_ALL:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for table, (_predicate, commands) in POLICIES.items():
        for command in commands:
            op.execute(f"DROP POLICY IF EXISTS {_policy_name(command)} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
