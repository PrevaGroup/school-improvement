"""scoring — a teacher's edit to the drafted message is a write, so the API needs to make it

0018 granted `sip_app` SELECT on `artifact_composition` and nothing more, which was right when
composing was a batch job and the console only read packets. A teacher editing the message before
it goes out is the API writing one.

INSERT only. `artifact_composition` is append-only by trigger, and an edit writes a NEW row
pointing at the one it replaces — so the packet a teacher reviewed stays exactly as it was, beside
the version they sent. That distinction is the whole reason the table is append-only: "what the
machine drafted" and "what the teacher sent" are two different facts, and a system that overwrote
the first could never answer how much editing its drafts actually need.

Revision ID: 0020
Revises: 0019
"""
from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

APP_ROLE = "sip_app"


def upgrade() -> None:
    op.execute(f"GRANT INSERT ON artifact_composition TO {APP_ROLE};")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT ON artifact_composition FROM {APP_ROLE};")
