"""evals — what each run of the stop conditions found, and paired cases

Two things, and the first is the one that makes the other worth having.

## A finding that is not recorded is a check nobody ran

`stop_conditions.evaluate()` returns five verdicts and, until this table, nothing kept them. That
makes the most important question about a gate unanswerable: has it ever held, and when did it
start failing? A gate whose history is not written down cannot distinguish "this has been fine for
three months" from "nobody has run it since June", and those are the two readings a green result
is most often given.

It also matters for the pre-commitment rule. `threshold_value`, `agreed_by` and `agreed_on` are
copied ONTO the row rather than referenced, so a finding records the number that was in force when
it was measured. Reading the current threshold instead would let somebody relax a number in
January and have December's runs retroactively pass — which is precisely the "explained rather
than acted on" failure the whole design exists to prevent.

## Paired cases

The plan: "eval_case gains a kind — mined, seeded, or paired — and the harness gains a comparison
runner that executes both arms under identical configuration and grades the delta against a
tolerance."

Three of the five conditions are comparisons rather than measurements. Cohort invariance is the
same paper in different company; matched pairs is the same paper with conventions errors added;
scrutiny invariance is the same paper at two escalation levels. In each the interesting number is
a DELTA, and neither arm alone means anything — which is why `pair_id` and `arm` live on the case
rather than being reconstructed from tags afterwards.

`pair_id` groups the arms and `arm` names which one this is. A case with a `pair_id` and no
sibling is a broken pair, and the runner refuses it rather than grading one arm against nothing.

Revision ID: 0030
Revises: 0029
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

# `mined` from real traffic, `seeded` written by hand, `paired` one arm of a comparison. The
# distinction is not bookkeeping: a mined case reflects what people actually do and a seeded one
# reflects what somebody thought to ask, and a suite made only of the second measures its author.
KINDS = ("mined", "seeded", "paired")

VERDICTS = ("holds", "triggered", "uncommitted", "insufficient")


def upgrade() -> None:
    op.add_column("eval_case", sa.Column("kind", sa.Text(), nullable=False,
                                         server_default="seeded"))
    # Which comparison this case belongs to, and which side of it. Null for a case that stands
    # alone, which is most of them.
    op.add_column("eval_case", sa.Column("pair_id", sa.Text()))
    op.add_column("eval_case", sa.Column("arm", sa.Text()))

    op.execute("ALTER TABLE eval_case ADD CONSTRAINT kind "
               "CHECK (kind IN (" + ",".join(f"'{k}'" for k in KINDS) + "));")
    # A pair needs both halves named or neither. Half a pair is a case that will be graded against
    # nothing and reported as a delta of zero — a passing result produced by an absence.
    op.execute("ALTER TABLE eval_case ADD CONSTRAINT a_pair_names_both_halves "
               "CHECK ((pair_id IS NULL AND arm IS NULL) OR "
               "       (pair_id IS NOT NULL AND arm IS NOT NULL));")
    op.execute("ALTER TABLE eval_case ADD CONSTRAINT paired_cases_are_paired "
               "CHECK (kind <> 'paired' OR pair_id IS NOT NULL);")
    op.create_index("ix_eval_case_pair", "eval_case", ["pair_id"])

    op.create_table(
        "eval_stop_condition",
        sa.Column("finding_id", sa.Text(), primary_key=True),
        sa.Column("eval_run_id", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        # Null when the verdict is `insufficient`: there was no number.
        sa.Column("observed", sa.Float()),

        # THE THRESHOLD AS IT STOOD, copied not referenced. A finding must not change meaning
        # because somebody later moved the line.
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("agreed_by", sa.Text()),
        sa.Column("agreed_on", sa.Text()),

        sa.Column("n", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=False),
        # The numbers under the number: per-criterion severities, per-subgroup rates, the pairs
        # that moved. A verdict with no breakdown is the uninformative summary that `teacher
        # acceptance` exists to detect, arriving one layer up.
        sa.Column("breakdown", postgresql.JSONB()),

        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="public"),

        sa.CheckConstraint("verdict IN (" + ",".join(f"'{v}'" for v in VERDICTS) + ")",
                           name="verdict"),
        # A verdict that stops a release must name who agreed it could. This is the pre-commitment
        # rule in the database rather than only in Python — the module is one way to write this
        # table and a script is another, the same argument as the release authority trigger.
        sa.CheckConstraint(
            "verdict <> 'triggered' OR (agreed_by IS NOT NULL AND agreed_on IS NOT NULL)",
            name="a_stop_names_who_agreed_to_it"),
        sa.CheckConstraint("verdict <> 'insufficient' OR observed IS NULL",
                           name="insufficient_has_no_number"),
    )
    op.create_index("ix_eval_stop_condition_run", "eval_stop_condition",
                    ["eval_run_id", "condition"])
    # The question this table exists to answer: when did this condition last hold, and when did it
    # start failing?
    op.create_index("ix_eval_stop_condition_history", "eval_stop_condition",
                    ["tenant_id", "condition", "created_at"])

    op.execute("GRANT SELECT ON eval_stop_condition TO sip_app;")


def downgrade() -> None:
    op.drop_table("eval_stop_condition")
    op.drop_index("ix_eval_case_pair", table_name="eval_case")
    for c in ("paired_cases_are_paired", "a_pair_names_both_halves", "kind"):
        op.execute(f"ALTER TABLE eval_case DROP CONSTRAINT IF EXISTS {c};")
    for c in ("arm", "pair_id", "kind"):
        op.drop_column("eval_case", c)
