"""serving reads the names a set is known by

The assignment home groups papers by the binding key a teacher actually names — this class,
this task — and to show a set it has to render `roster_section.name` and `registry_task.name`.
Every other table that page touches was already granted to the API role by the module that owns
it; these two were not, because until now nothing served them.

## Why this is a migration rather than an assumption

The bootstrap sets ALTER DEFAULT PRIVILEGES for tables created by `sip_migrator`, so these
grants are very likely already in place. "Very likely" is the problem. A missing SELECT surfaces
as a `SQLAlchemyError`, and the home endpoint's honest-degradation path turns any such error
into `available: false` — which the console renders as "nothing has been read yet". A permission
error would therefore appear as an empty, calm, entirely wrong page, with no error anywhere.

That is the defect this codebase keeps finding: a thing reporting success while not doing the
job. `GRANT` is idempotent, so asserting it costs nothing and removes the failure mode.

## Why the module that READS writes the grant

Precedent, and it is the right way round: 0022 is a `scoring` migration granting SELECT on
intake's tables, and 0024 is intake granting on its own. The grant records a dependency, and the
dependency belongs to whoever took it on. `registry` and `roster` do not know serving exists and
should not have to.

Revision ID: 0026
Revises: 0025
"""
from __future__ import annotations

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

APP_ROLE = "sip_app"

# READ ONLY, and named table by table. `GRANT SELECT ON ALL TABLES` would hand the API role
# every future registry and roster table by default, including ones added for reasons that have
# nothing to do with serving — the same argument as the column-level UPDATE grant in 0018.
TABLES = ("registry_task", "roster_section")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {APP_ROLE};")


def downgrade() -> None:
    # Deliberately not revoked. These grants are very likely inherited from the bootstrap's
    # default privileges, and a downgrade that revoked them would take away a privilege this
    # migration may never have granted — breaking readers that predate it.
    pass
