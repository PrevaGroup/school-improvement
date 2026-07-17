"""Drop usage_chat_daily.principal_email — usage is metered anonymously.

Privacy posture (decided 2026-07-17): the app does not store or display user identity.
Spend metering keys on the OPAQUE `principal_sub` (a rate-limit/cost key), and analytics
traces are pseudonymous (salted hash of the sub, never email — see app/traces.py). The
`principal_email` column (added by 0005) was ride-along ops metadata never used by the cap
logic; dropping it both removes the write and PURGES the emails already retained, so the
claim "usage is metered anonymously; we don't store your identity" is true of the data at
rest, not just going forward.

Deploy order: ship the app code that stops writing this column FIRST, then run this migration.
`record_chat_usage` never raises, so an out-of-order drop only under-counts one message rather
than erroring — but code-first keeps it clean.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("usage_chat_daily", "principal_email")


def downgrade() -> None:
    # Re-add nullable; the purged values do not come back (they are gone by design).
    op.add_column(
        "usage_chat_daily",
        sa.Column("principal_email", sa.Text(), nullable=True),
    )
