"""registry — one judgment that answers several findings is one decision, not several

The linter reports stacked conditionals per CATEGORY, so a rubric row with the problem in all four
cells produces four findings. A reviewer looking at that row makes ONE judgment about it. Writing
four acknowledgment rows with no link between them records four reviews that never happened, and
a later count of "how many findings has anyone actually looked at" would be wrong in the flattering
direction.

`score_event.set_override_id` exists for exactly this, in exactly these words: "a set-level
override is ONE judgment covering many artifacts. Recorded as one decision so it is not counted as
N independent human ratings, which would inflate apparent disagreement and hide that a single
judgment was made once." The same sentence applies here with the nouns changed, so the same shape
follows.

Nullable: a single-finding acknowledgment is its own decision and does not need an id to say so.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("registry_lint_acknowledgment", sa.Column("decision_id", sa.Text()))
    op.create_index("ix_registry_lint_ack_decision", "registry_lint_acknowledgment",
                    ["decision_id"])


def downgrade() -> None:
    op.drop_index("ix_registry_lint_ack_decision", "registry_lint_acknowledgment")
    op.drop_column("registry_lint_acknowledgment", "decision_id")
