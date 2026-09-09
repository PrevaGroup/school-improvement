"""corpus_paper gains the assignment and the source text

Both columns were in `persuade_2.0_human_scores_demo_id_github.csv` from the first load and
neither was mapped. Nothing downstream complained, because nothing could: a paper with no task
statement scores fine, and a source-based evidence trait judged without the source produces a
number that looks like any other number.

## What their absence did to the measurement

`assignment` is the task statement. `scoring.fit` short-circuits when there is none — deliberately,
because no task statement means no gate — so every corpus paper skipped stage B, which student
work does not. The severity estimated on the anchor set therefore describes a rater running one
stage fewer than the one in production.

`source_text` is the reading supplied with a text-dependent prompt. The evidence trait for that
form is defined as evidence "taken from the source text(s)". Nothing in the pipeline had ever seen
a source text, so that trait asked whether a quotation came from a document the rater could not
read. That is a validity problem in the trait as specified, not a tuning question, and it applied
to 163 of the 334 anchor papers.

## What is still genuinely missing

The element effectiveness ratings. The headers settle it: both files carry `discourse_type` and
neither carries `discourse_effectiveness`. The loader's comment saying so was correct.

## Backfilling

`corpus_paper` upserts on (source_id, external_id), so re-running the loader fills these in for the
25,990 papers already there. `--papers-only` exists for exactly this: adding a column to
`corpus_paper` should not mean re-reading 800MB of segmentation to change nothing in it.

Nullable, because a corpus that supplies neither is a corpus this system should still be able to
hold — and because an independent prompt HAS no source text, so NULL there is the fact rather than
a gap.

Revision ID: 0039
Revises: 0038
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("corpus_paper", sa.Column("assignment", sa.Text()))
    op.add_column("corpus_paper", sa.Column("source_text", sa.Text()))


def downgrade() -> None:
    op.drop_column("corpus_paper", "source_text")
    op.drop_column("corpus_paper", "assignment")
