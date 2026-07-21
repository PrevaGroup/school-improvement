"""Drop usage_chat_daily.principal_email — usage is metered anonymously.

Privacy posture (decided 2026-07-17): the app does not store or display user identity.
Spend metering keys on the OPAQUE `principal_sub` (a rate-limit/cost key), and analytics
traces are pseudonymous (salted hash of the sub, never email — see app/traces.py). The
`principal_email` column (added by 0005) was ride-along ops metadata never used by the cap
logic; dropping it both removes the write and PURGES the emails already retained.

Revision-chain note (fixed 2026-07-21): this was first authored as `0006`, colliding with the
evals module's `0006_eval_tables` (both off `0005`) — a duplicate revision id that made
`alembic upgrade head` silently apply only ONE of the two. Renumbered to `0007` with
down_revision `0006`, linearizing 0005 → 0006 (eval_tables) → 0007 (this). The DROP is now
`IF EXISTS` so a reconciliation re-run is a safe no-op whichever migration ran the first time.

Deploy order: ship the app code that stops writing this column FIRST, then run this migration.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: the duplicate-0006 collision means this may already have run under the old id.
    op.execute("ALTER TABLE usage_chat_daily DROP COLUMN IF EXISTS principal_email")


def downgrade() -> None:
    # Re-add nullable; the purged values do not come back (they are gone by design).
    op.add_column(
        "usage_chat_daily",
        sa.Column("principal_email", sa.Text(), nullable=True),
    )
