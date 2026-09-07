"""a scoring configuration declares how many times it may look

`score_event.scrutiny_passes` and `escalation_trigger` have existed since 0008. Nothing wrote
anything but 1 and NULL, because there was no escalation — and there was no escalation partly
because there was nowhere to declare its rules. A budget hard-coded in `run_scoring.py` would be
a spending decision made by whoever last edited a Python file.

## Why it belongs on the configuration and not in the code

The expansion plan requires escalation to run "on declared deterministic triggers, with a fixed
budget and a declared terminal action". Declared means somebody published it: the configuration
is already the object an administrator promotes with a rationale and a second approver, and it is
already the thing stamped on every event as the rater's identity. How deep the rater is allowed
to look is part of what that rater is.

It also makes the answer to the open turnaround question a configuration change rather than a
deploy. Next-day grading makes the budget a cost decision; same-period would have made it a
latency decision, with a smaller number. Neither should require a code review.

## Why it is NOT in `definition_hash`, which is a real trade

`definition_hash` covers model, effort, prompts and normalisation — the things that decide what a
score MEANS. Escalation decides how many chances a criterion gets to produce one, which is
adjacent but not the same: an escalated event already stamps `scrutiny_passes`, the rule that
fired, and a different `effort` on its own row, so what happened is fully recoverable per event
without the policy being in the hash.

The counter-argument is real and worth writing down rather than winning: two configurations that
differ only in budget do produce different bodies of scores, and someone doing a strict replay
would want them to hash differently. Including it would mean that raising a budget re-rates every
paper ever scored. That is a bigger call than this migration should make quietly, and the per-row
stamps mean nothing is lost by deferring it.

## The default is absence

A NULL column is the default policy, which is what every configuration written before today has.
`escalate.Policy.from_config(None)` returns it. Backfilling a literal would claim those
configurations declared something they never did.

Revision ID: 0027
Revises: 0026
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("registry_scoring_configuration",
                  sa.Column("escalation", postgresql.JSONB()))

    # The shape is checked in `scoring/escalate.py`, where the reasoning is. What the database
    # enforces is the one thing a typo could quietly destroy: a budget that is absent means the
    # default, and a budget that is present must be a number a run can actually spend. A negative
    # budget would silently disable escalation on a configuration whose author thought they had
    # turned it up.
    op.execute("""
    ALTER TABLE registry_scoring_configuration
      ADD CONSTRAINT escalation_budget_is_spendable
      CHECK (escalation IS NULL
             OR escalation->'budget' IS NULL
             OR ((escalation->>'budget') ~ '^[0-9]+$' AND (escalation->>'budget')::int <= 20));
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE registry_scoring_configuration "
               "DROP CONSTRAINT IF EXISTS escalation_budget_is_spendable;")
    op.drop_column("registry_scoring_configuration", "escalation")
