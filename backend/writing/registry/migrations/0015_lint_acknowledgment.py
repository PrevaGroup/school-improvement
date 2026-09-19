"""registry — somewhere for an advisory acknowledgment to live

The linter has two classes and the difference is the whole design. Blocking means the registry is
internally incoherent and publication is refused. Advisory means a judgment the linter cannot make
— and the contract says those "clear only with a recorded acknowledgment naming a reason, and the
acknowledgment becomes part of the version record, so the next reader sees a judgment that was made
rather than a check that was skipped."

`lint()` implements the clearing half: an advisory finding whose "rule:subject" appears in
`Registry.acknowledgments` is dropped. Nothing implemented the recording half. There was no table,
nothing populated the field, and the first real lint pass printed four advisory findings that went
nowhere. An advisory class with no way to answer it is a warning log, which is the thing the two
classes exist to not be.

WHY A TABLE AND NOT A COLUMN. `registry_node_version.construct_unchanged_ack` already exists and is
NOT this: it answers one specific blocking rule (did a descriptor edit clarify the construct or
replace it). An acknowledgment here is one judgment about one (rule, subject) pair, one version can
carry several, and each needs its own author and reason. Folding many judgments into one column
loses which was answered and by whom, which is the same hidden-facet mistake as folding form
variant into rubric version.

Not frozen and not append-only. A judgment can be withdrawn when someone decides the finding
deserved a fix after all, and making that hard would push people toward not recording one.

Revision ID: 0015
Revises: 0014
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registry_lint_acknowledgment",
        sa.Column("ack_id", sa.Text(), primary_key=True),
        sa.Column("rule", sa.Text(), nullable=False),
        # The finding's subject as the linter names it — a node id, or "node-version:category".
        sa.Column("subject", sa.Text(), nullable=False),
        # The version record this becomes part of. Nullable because some findings are about a node
        # rather than a version, and forcing a version onto those would be a lie about their scope.
        sa.Column("node_version_id", sa.Text(),
                  sa.ForeignKey("registry_node_version.node_version_id")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("acknowledged_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        # One standing answer per finding. Re-acknowledging updates the reason rather than
        # stacking a second one, so "what did we decide" has one answer.
        sa.UniqueConstraint("rule", "subject", name="uq_registry_lint_ack_finding"),
        # A reason that says nothing is the check being skipped with extra steps.
        sa.CheckConstraint("length(btrim(reason)) >= 12", name="reason_substantive"),
    )
    op.create_index("ix_registry_lint_ack_version", "registry_lint_acknowledgment",
                    ["node_version_id"])


def downgrade() -> None:
    op.drop_table("registry_lint_acknowledgment")
