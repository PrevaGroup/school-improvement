"""corpus — an overlap can be declared before the other corpus is loaded

The write path's first real run failed here, and the failure was correct in mechanism and wrong in
policy:

    ForeignKeyViolation: Key (overlaps_source_id)=(asap2) is not present in table corpus_source

PERSUADE 2.0 declares that it shares 12,725 essays with ASAP2 at identical scores, and that every
ASAP prompt is a PERSUADE prompt — so they are not independent sources and a calibrate-on-one /
validate-on-the-other split across them would be circular.

That is true whether or not ASAP2 has been loaded into this database. The self-referencing foreign
key made recording it depend on load order, which means the fact could be lost by loading the two
corpora in the wrong sequence — and the moment it is most needed is precisely BEFORE somebody
loads the second one and starts treating them as independent.

## Why not resolve the link afterwards

The first fix attempted was to write the note now and set the id when the other corpus arrives,
matching the corpus name inside the note text. That is prose matching standing in for a
relationship, and it would silently stop working the day somebody rewords a note. A declaration
that points at something absent is more honest than a link that depends on a string.

## What is kept

The column, the note, and the index. Only the constraint goes. A reader asking "does this corpus
overlap anything" gets the same answer; a reader asking "is the thing it names loaded" joins and
finds nothing, which is the true answer rather than an impossible state.

Revision ID: 0031
Revises: 0030
"""
from __future__ import annotations

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

FK = "fk_corpus_source_overlaps_source_id_corpus_source"


def upgrade() -> None:
    op.execute(f"ALTER TABLE corpus_source DROP CONSTRAINT IF EXISTS {FK};")


def downgrade() -> None:
    # Deliberately not restored. Re-adding it would fail on exactly the row this migration exists
    # to allow, and a downgrade that cannot run on real data is worse than one that declines to.
    pass
