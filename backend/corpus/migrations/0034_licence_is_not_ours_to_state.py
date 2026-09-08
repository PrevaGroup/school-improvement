"""clear the licence this project asserted about somebody else's corpus

`corpus_source.licence` for `persuade20` says `CC BY 4.0`, and `registry_rubric.source` for the
four PERSUADE rubrics carries the same string. Neither was read from the distribution. It was a
literal in `corpus/load_persuade.py` and another in `registry/seed_persuade.py`, written from
memory by this project, and two tests asserted those literals — so CI defended the claim.

Nobody here is PERSUADE's licensor. The terms can differ between the corpus and the rating forms,
they can change between snapshots, and a permissive licence invented on our side is the error that
actually costs something: it authorises redistribution the publisher may not grant. The direction
of the error is the whole problem — an overly RESTRICTIVE guess makes somebody go and check, and a
permissive one makes them proceed.

## Why NULL rather than the correct string

Because writing the correct string here would be the same act that caused this. A licence arrived
at by reading a message, or by remembering, is not sourced no matter which licence it names.

NULL is not "this corpus has no terms" — it is "this database does not claim to know them", and
`corpus._shared.read_licence` now makes the next load establish it: the spec names a file that
ships with the download, the loader stores what that file says verbatim, and a declared file that
is missing FAILS the load rather than defaulting.

So this migration leaves a gap that the next load must fill from the source. That is the point.

## What is safe to keep

`registry_rubric.source` keeps its provenance — which rating form, transcribed on which date —
and gains the publisher's URL in place of the licence name. Where the terms are stated is a fact
about where to look, and it does not expire the way a remembered licence does.

Revision ID: 0034
Revises: 0033
"""
from __future__ import annotations

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

TERMS_URL = "https://github.com/scrosseye/persuade_corpus_2.0"


def upgrade() -> None:
    op.execute("""
        UPDATE corpus_source
           SET licence = NULL
         WHERE source_id = 'persuade20'
           AND licence = 'CC BY 4.0'
    """)
    # Only the rows that carry the asserted string, and only the licence part of it. A blanket
    # rewrite of `source` would destroy the transcription date and the form name, which are ours
    # to state and are the reason the column exists.
    op.execute(f"""
        UPDATE registry_rubric
           SET source = replace(source, ' (CC BY 4.0)', '')
                        || ' — terms as stated at {TERMS_URL}'
         WHERE source LIKE '%%CC BY 4.0%%'
           AND source LIKE '%%PERSUADE%%'
    """)


def downgrade() -> None:
    # Deliberately does NOT restore the string. A downgrade that reinstates a false licence claim
    # is a downgrade that reintroduces the defect, and the schema is unchanged either way — there
    # is nothing here for a downgrade to make runnable again.
    pass
