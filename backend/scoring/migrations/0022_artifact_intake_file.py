"""scoring — where an artifact came from

`artifact.source_uri` pointed at a file on local disk, which worked while the pipeline was one
batch job on one machine. Intake now extracts text once at read time and stores it, so an artifact
points at the `intake_file` row it was made from instead.

That column is also how "has this file been bound yet" is answered without either module writing
the other's tables: `scoring/bind.py` looks for intake rows with no artifact referencing them. The
alternative — an `artifact_id` column on `intake_file`, set by scoring — would have scoring writing
intake's table, which `tests/test_table_ownership.py` refuses and which would make the writes run
both ways for no gain.

No foreign key. `intake_file` belongs to another module, and a cross-module FK is a coupling the
producer/consumer cut exists to avoid — it would make dropping and reloading a manifest a scoring
problem. The reference is by value, checked where it is read.

Revision ID: 0022
Revises: 0021
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("artifact", sa.Column("intake_file_id", sa.Text()))
    op.create_index("ix_artifact_intake_file", "artifact", ["intake_file_id"])
    # The console reads the paper text through the artifact, and the text now lives in intake.
    op.execute("GRANT SELECT ON intake_file, intake_manifest TO sip_app;")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON intake_file, intake_manifest FROM sip_app;")
    op.drop_index("ix_artifact_intake_file", "artifact")
    op.drop_column("artifact", "intake_file_id")
