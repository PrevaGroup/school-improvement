"""persist fit statistics, so an unexpected score can be found rather than stumbled on

`measurement/CLAUDE.md` said: "Do not add estimator output tables yet. Facet estimates, fit
statistics and bias interactions belong to Phase 6, when the estimator exists and its output shape
is known rather than guessed." The estimator now exists, has run against 334 real papers twice, and
its output shape is `mfrm.Element` — measure, se, n, infit, outfit, and whether the element was
extreme. These tables are that shape, not a guess at it.

## What the statistics are for

A severity is about a RATER. Fit is about whether the model describes what happened at all, and
its per-person form answers a question a teacher actually has: do this paper's scores hang
together? A paper scoring 3, 3, 3, 1, 3, 3, 3 across seven traits contains one response the model
did not expect, and that is worth a second look — not because the low score is wrong, but because
something inconsistent happened and nobody can see it in a mean.

Outfit is the flag. It is driven by outliers, which is exactly the case here; infit is stored
beside it because a paper that is mildly odd everywhere is a different problem from one that is
wildly odd once.

## Why a run is scoped to ONE SCALE

The rating scale model estimates thresholds between adjacent categories, and those thresholds are
a property of the scale. A holistic trait on 1-6 and an element on 1-3 do not share them, so a fit
that mixes them is estimating a scale nobody used. `scale_categories` is on the run and a check
constraint requires it; `measurement.fit_run` refuses to build a run from mixed scales.

That is also why holistic traits cannot get a person fit here: one holistic trait per paper is one
observation per person, and one observation has no residual.

## What an extreme element is, and why it is a row rather than an omission

A paper scored at the very top or the very bottom of the scale on every trait has an infinite
measure in the model and is excluded from estimation. Dropping it would make a class of papers
quietly absent from every count. It gets a row with `extreme` set and no measure, which is the
difference between "not estimable" and "not present".

Revision ID: 0040
Revises: 0039
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

FACETS = ("person", "rater")


def upgrade() -> None:
    op.create_table(
        "measurement_fit_run",
        sa.Column("run_id", sa.Text(), primary_key=True),
        # WHAT WAS FITTED. A fit is only interpretable against the scores it was fitted over, and
        # those are identified the way every score in this system is: by binding and by rater.
        sa.Column("section_id", sa.Text()),
        sa.Column("task_id", sa.Text()),
        sa.Column("iteration", sa.Text()),
        sa.Column("scoring_configuration_id", sa.Text(), nullable=False),
        # The scale this run covers. One run, one scale — see the module docstring.
        sa.Column("scale_categories", postgresql.JSONB(), nullable=False),
        sa.Column("node_ids", postgresql.JSONB(), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("persons", sa.Integer(), nullable=False),
        sa.Column("thresholds", postgresql.JSONB()),
        sa.Column("iterations", sa.Integer()),
        # A fit that did not converge is not a fit. Recorded rather than discarded, because
        # "the estimator gave up on this class" is a finding and an empty table is not.
        sa.Column("converged", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.CheckConstraint("jsonb_array_length(scale_categories) >= 2", name="scale_fittable"),
        sa.CheckConstraint("jsonb_array_length(node_ids) >= 2", name="two_traits_minimum"),
    )
    op.create_index("ix_measurement_fit_run_binding", "measurement_fit_run",
                    ["tenant_id", "section_id", "task_id", "iteration"])

    op.create_table(
        "measurement_fit_element",
        sa.Column("run_id", sa.Text(), sa.ForeignKey("measurement_fit_run.run_id"),
                  primary_key=True),
        sa.Column("facet", sa.Text(), primary_key=True),
        # A person here is an ARTIFACT, not a student. The unexpected thing is a property of one
        # piece of writing, and attributing it to the writer would make it a claim about them.
        sa.Column("element_id", sa.Text(), primary_key=True),
        sa.Column("measure", sa.Numeric()),
        sa.Column("se", sa.Numeric()),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("infit", sa.Numeric()),
        sa.Column("outfit", sa.Numeric()),
        # A sentence, not a code — "every rating at the top category". It surfaces to a
        # reader, and "top" would need a glossary to mean anything. No measure exists; the
        # row does.
        sa.Column("extreme", sa.Text()),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.CheckConstraint("facet IN (" + ",".join(f"'{f}'" for f in FACETS) + ")", name="facet"),
        # A measure without a standard error cannot be read, and an extreme element has neither.
        sa.CheckConstraint("(measure IS NULL) = (se IS NULL)", name="measure_carries_its_error"),
        sa.CheckConstraint("extreme IS NULL OR measure IS NULL", name="extreme_has_no_measure"),
    )
    op.create_index("ix_measurement_fit_element_outfit", "measurement_fit_element",
                    ["run_id", "facet", "outfit"])


def downgrade() -> None:
    op.drop_table("measurement_fit_element")
    op.drop_table("measurement_fit_run")
