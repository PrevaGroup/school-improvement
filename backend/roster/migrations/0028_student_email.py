"""a student's account address, so a match can be a lookup instead of an inference

`reconcile()` has scored an account match at 100 against a name similarity of at most 1.0 since it
was written — a deliberate gap, so an account always outbids a name — and it reads
`student["email"]` to do it. `roster_student` has never had the column. Every match in the system
is therefore `inferred`, and `Manifest.inferred_rate` has read 1.0 on every run.

## Why this is not cosmetic

The contract says it plainly: "A score whose binding was inferred has a different error profile
from one looked up — pooling them pools two populations." A name read off a filename can be wrong
in ways an account cannot: two students who share a surname, a file named after the assignment
rather than the writer, a nickname. Attaching a score to the wrong student attaches it to the wrong
trajectory, and growth over a wrong pair is worse than no growth claim at all.

It is also the only thing that makes the Drive integration pay for itself in accuracy rather than
in convenience. Drive supplies `owner_email` and `editor_emails`; without a roster address to
compare them to, the integration would enumerate faster and still infer every match.

## Nullable, and it stays nullable

A roster without addresses is the normal case for a CSV import, and a NOT NULL here would make one
missing address reject a whole class. An absent address means the matcher falls back to the name
path and records `inferred`, which is exactly what it should do — the honesty is in the
`resolution_path` column, not in refusing the row.

## Not unique, deliberately

Two roster rows can carry one address: a student enrolled in two sections is two enrolments but a
shared account, and a shared family address is real in younger grades. Uniqueness would reject
those. What matters for matching is the reverse direction — one file's owner resolving to at most
one student IN THIS SECTION — and the solver enforces that as a one-to-one assignment over the
section roster, which is a constraint no column can express.

Revision ID: 0028
Revises: 0027
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("roster_student", sa.Column("email", sa.Text()))
    # Case-insensitive, because an address is. `reconcile()` lowercases both sides before
    # comparing; the index has to agree or it is decorative on exactly the lookups it exists for.
    op.execute("CREATE INDEX ix_roster_student_email "
               "ON roster_student (tenant_id, lower(email)) WHERE email IS NOT NULL;")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_roster_student_email;")
    op.drop_column("roster_student", "email")
