"""a tenant for corpus papers, so they never appear in a teacher's queue

Corpus papers have to go through the SAME pipeline as student work — fit gate, evidence
extraction, span verification, the configuration pin — or the severity estimated from them
describes a rater that never touches a real paper. That means they need artifacts, and artifacts
are what the teacher's review console reads.

Six hundred and sixty-four PERSUADE essays arriving in a teacher's queue is not a small annoyance;
it is the console becoming useless and somebody releasing feedback on an essay written by a
stranger in 2018.

## Why a tenant rather than a flag

The alternative was a boolean on `artifact` and a `WHERE NOT is_corpus` in every query that reads
it. That is a filter somebody forgets exactly once, in a query nobody reviews, and the failure is
silent. Tenancy is already the mechanism this system uses to keep one district's papers out of
another's, every artifact already carries `tenant_id`, and the console already scopes to `public`.
Reusing it means corpus papers are invisible by default rather than by remembering.

It also means the counts are right for free. `/api/review/home` groups by binding key within a
tenant, so a corpus paper cannot inflate a class's total no matter how the query is written later.

## What it is not

Not a district, and `tenant_type` says `corpus` rather than borrowing one. It owns no schools, has
no jurisdiction, and nothing about it should resolve through the roster or the school hierarchy —
a `tenant_scope` row here would let corpus papers claim a real school.

Revision ID: 0032
Revises: 0031
"""
from __future__ import annotations

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

TENANT = "corpus"


def upgrade() -> None:
    op.execute("""
        INSERT INTO dim_tenant (tenant_id, tenant_type, display_name, jurisdiction)
        VALUES ('corpus', 'corpus',
                'Reference corpora — anchor papers, not student work in this system', NULL)
        ON CONFLICT (tenant_id) DO NOTHING
    """)


def downgrade() -> None:
    # Only if nothing is in it. Removing a tenant that owns artifacts would orphan every score
    # written against them, and a downgrade that can destroy a calibration is worse than one that
    # declines to run.
    op.execute("""
        DELETE FROM dim_tenant
         WHERE tenant_id = 'corpus'
           AND NOT EXISTS (SELECT 1 FROM artifact WHERE tenant_id = 'corpus')
    """)
