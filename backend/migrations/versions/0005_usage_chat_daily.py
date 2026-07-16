"""usage_chat_daily — the Claude spend counter for /api/chat (core operational state).

The §3.4 gate blocker: --no-allow-unauthenticated currently caps Anthropic spend by capping
WHO can call; this table is what lets the app cap spend itself so that gate can come off.
Raw token counts at (principal, UTC day, model) grain; dollars derived in app/usage.py.

Core-owned by decision (docs/MODULES.md): serving writes it through core, the way it uses
db.py — it is platform bookkeeping, not a serving data product. No RLS: keyed by verified
principal, never tenant data, never served through the API.

Revision chain note: 0004 lives in likeschools/migrations (module-owned, wired via
version_locations); this core table goes in the core spine with down_revision pointing at it.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_chat_daily",
        sa.Column("principal_sub", sa.Text(), primary_key=True),
        sa.Column("usage_date", sa.Date(), primary_key=True),
        sa.Column("model", sa.Text(), primary_key=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cache_read_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cache_creation_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("principal_email", sa.Text(), nullable=True),
    )
    # The global-cap check scans one day across all users; the PK covers the per-user check.
    op.create_index("ix_usage_chat_daily_date", "usage_chat_daily", ["usage_date"])
    # Bootstrap's ALTER DEFAULT PRIVILEGES already grants sip_app on new sip_migrator tables;
    # explicit anyway, matching 0001's stated belt-and-braces pattern.
    op.execute("GRANT SELECT, INSERT, UPDATE ON usage_chat_daily TO sip_app")


def downgrade() -> None:
    op.drop_index("ix_usage_chat_daily_date", table_name="usage_chat_daily")
    op.drop_table("usage_chat_daily")
