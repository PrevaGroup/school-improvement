"""drop `corpus_source.licence` — licensing is not this system's to hold

0034 stopped this repo from ASSERTING a licence and made the loader read one from the
distribution. That fixed the wrong half of the problem. The remaining half is the column: a
better-sourced licence field is still this system holding a fact that belongs somewhere else.

## Why a copy here is worse than no copy

Terms are negotiated, and they change without the data changing. A licence copied into
`corpus_source` is a second record of an agreement whose first record lives elsewhere — so it goes
stale silently while continuing to look authoritative, and the moment it is consulted is the
moment somebody is deciding whether they may redistribute something. That is the worst possible
time to be reading a stale copy.

The original defect makes the point. The column held `CC BY 4.0` for PERSUADE, written from
memory, and two tests asserted it — so the wrong answer was available, confident, and defended by
CI. Every mechanism that made it trustworthy-looking was working exactly as designed.

Licensing lives in the contracts system. This one keeps `url`, which points at the publisher: who
published a corpus is provenance and is ours to record. What may be done with what they published
is not.

## The registry rows too

0034 appended " — terms as stated at <url>" to the PERSUADE rubric `source` strings. That was the
same mistake one step removed — a pointer to terms is still this system carrying licensing. It is
stripped here, leaving the provenance that belongs: which rating form, transcribed on what date.

Revision ID: 0035
Revises: 0034
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("corpus_source", "licence")
    op.execute("""
        UPDATE registry_rubric
           SET source = split_part(source, ' — terms as stated at ', 1)
         WHERE source LIKE '%% — terms as stated at %%'
    """)


def downgrade() -> None:
    # The column comes back empty. Restoring values would mean re-inventing the claim this
    # migration exists to remove, and there is nothing to restore them FROM — 0034 already set the
    # only row to NULL, correctly.
    op.add_column("corpus_source", sa.Column("licence", sa.Text(), nullable=True))
