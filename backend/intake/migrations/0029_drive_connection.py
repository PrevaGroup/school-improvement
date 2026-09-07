"""intake — whose Drive is connected, and by whom

Per-teacher OAuth, not domain-wide delegation. The plan settles that: domain-wide only becomes the
right call at district scale, where central provisioning starts to outweigh blast radius. One
teacher's refresh token reaches one teacher's Drive; a delegated service account reaches everyone's,
including staff files that have nothing to do with this product.

## Two identities, and the reason this table has two columns for them

The person signed into the console and the Google account whose Drive is being read are NOT
necessarily the same. In the pilot they demonstrably are not: the console principal is a personal
address on the invite list, and the folders live in a Workspace account. A table that recorded only
one of them could not answer "whose Drive did this folder come from" — and that is the question
asked when a paper turns out to be somebody else's, or when a person leaves and their access has to
go with them.

So `principal_sub` is who connected it (the verified subject from the console's own sign-in, never
a client-supplied field) and `google_email` is whose Drive it reaches.

## This table holds no credentials

`token_secret_name` is a POINTER into Secret Manager, where every other secret this system holds
already lives. The first draft of this migration put the refresh token in a column and explained
that Cloud SQL encrypts at rest and no query selects it — which describes a mitigation rather than
a place for a credential, and left a live token visible to a `pg_dump`, a debugging session, a
migration, or a future serving query written by somebody who did not read the comment.

With a pointer, the token is under IAM instead of a table grant: auditable per read in Cloud Audit
Logs, revocable without a deploy, and grantable to exactly the service account that needs it. A
`GRANT SELECT` expresses none of that.

Access tokens are not stored anywhere. They live about an hour, so a stored one is stale far more
often than useful.

## Revocation is a row, not a delete

`revoked_at` rather than DELETE, for the same reason every other record in this subsystem appends:
a manifest read six weeks ago was read through a connection, and deleting the row would make the
provenance of those papers unrecoverable. A revoked connection is unusable and still explains where
existing work came from.

Revision ID: 0029
Revises: 0028
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intake_drive_connection",
        sa.Column("connection_id", sa.Text(), primary_key=True),
        # WHO connected it: the verified subject from the console's sign-in.
        sa.Column("principal_sub", sa.Text(), nullable=False),
        sa.Column("principal_email", sa.Text()),
        # WHOSE Drive it reaches. Different from the above whenever somebody signs in with one
        # account and authorises another, which is the pilot's actual shape.
        sa.Column("google_email", sa.Text(), nullable=False),

        # A Secret Manager secret id, never the credential. See `intake/token_store.py`.
        sa.Column("token_secret_name", sa.Text(), nullable=False),
        # Exactly what was granted, as Google returned it — not as we asked for it. A consent
        # screen where the user unticked a scope returns less than was requested, and an
        # enumeration that then fails should say "you did not grant Docs" rather than 403.
        sa.Column("granted_scopes", sa.Text(), nullable=False),

        sa.Column("connected_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True)),
        # A refresh token that stops working is the normal end of a connection, not an error worth
        # paging about: on an External/Testing consent screen Google expires them after 7 days.
        # Recorded so the console can say "reconnect" instead of failing a folder read.
        sa.Column("failed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("failure_detail", sa.Text()),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("revoked_by", sa.Text()),

        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),

        # A failure has to say what failed, like every other failure record here. "Reconnect" with
        # no reason is the message a person cannot act on.
        sa.CheckConstraint("failed_at IS NULL OR failure_detail IS NOT NULL",
                           name="a_failure_says_what_failed"),
    )

    # One LIVE connection per Google account per tenant. Connecting the same Drive twice is a
    # person clicking again, not a second connection — and two live rows would make "which token"
    # a coin toss. Revoked rows are excluded so a reconnect after revocation is allowed, which is
    # the whole point of keeping the old row.
    op.execute("""
    CREATE UNIQUE INDEX uq_intake_drive_connection_live
        ON intake_drive_connection (tenant_id, lower(google_email))
     WHERE revoked_at IS NULL;
    """)
    op.create_index("ix_intake_drive_connection_principal", "intake_drive_connection",
                    ["tenant_id", "principal_sub"])

    # The API needs to read a connection to use it and to write one when a person connects. It does
    # NOT get DELETE: a connection is revoked by setting a column, so the provenance of papers read
    # through it survives.
    op.execute("GRANT SELECT, INSERT ON intake_drive_connection TO sip_app;")
    # Nothing here is sensitive to read, which is the point: the row names a secret, and reading
    # the secret is an IAM decision made in Secret Manager rather than a table grant made here.
    op.execute("GRANT UPDATE (last_used_at, failed_at, failure_detail, revoked_at, revoked_by) "
               "ON intake_drive_connection TO sip_app;")


def downgrade() -> None:
    op.drop_index("ix_intake_drive_connection_principal", table_name="intake_drive_connection")
    op.execute("DROP INDEX IF EXISTS uq_intake_drive_connection_live;")
    op.drop_table("intake_drive_connection")
