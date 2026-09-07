"""intake — a folder read is a proposal until a teacher confirms it

The plan calls this the largest single saving in the design: one confirmation replacing
twenty-eight corrections. A folder read produces a set — these files, these students, this task,
this iteration — and a teacher agrees with the SET once rather than approving twenty-eight papers
one at a time.

Until now a read went straight to binding, with the declaration supplied as command-line flags.
That is not a gate; it is a script with arguments, and it works only because the person typing the
flags is the person who would have confirmed them.

## Why the gate has to exist in the data and not in the interface

`scoring.bind` reads these rows to create artifacts. If confirmation lived only in a screen, a
second entry point — a cron, a retry, somebody running the module directly — would bind an
unconfirmed read, and the papers would be scored against a declaration nobody agreed to. So
`confirmed_at` is the thing bind filters on, and the screen is one way to set it.

## What a confirmation asserts

Not that every match is right — a teacher can be wrong about a name. It asserts that the SET is
what they think it is: this folder is that class's final op-ed, these files are the submissions,
and the ones the system could not place are genuinely unplaceable rather than a broken
integration. The per-file corrections available before confirming are the exception the set
confirmation exists to make rare.

Revision ID: 0024
Revises: 0023
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("intake_manifest",
                  sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True)))
    op.add_column("intake_manifest", sa.Column("confirmed_by", sa.Text()))
    # A confirmation is somebody's. One without a name is a gate that opened by itself.
    op.create_check_constraint(
        "confirmation_is_attributed", "intake_manifest",
        "confirmed_at IS NULL OR confirmed_by IS NOT NULL")
    op.create_index("ix_intake_manifest_unconfirmed", "intake_manifest",
                    ["tenant_id", "confirmed_at"])

    # A teacher may correct a file's student before confirming, so the API role needs to write
    # these two columns and nothing else on the row. The rest of an intake_file — the text, the
    # hash, what the reconciler decided — is a record of a READ, and a read is not editable.
    op.execute("GRANT SELECT ON intake_manifest, intake_file TO sip_app;")
    op.execute("GRANT UPDATE (confirmed_at, confirmed_by) ON intake_manifest TO sip_app;")
    op.execute("GRANT UPDATE (resolved_student_id, status, resolution_basis, resolution_path, "
               "reason_code) ON intake_file TO sip_app;")

    op.execute("""
    -- A confirmed read is a decision, and the files under it stop being editable. Correcting a
    -- match after confirmation would change what a teacher agreed to without their agreeing to it
    -- again — and by then `scoring.bind` may already have made artifacts from these rows.
    CREATE FUNCTION intake_file_frozen_after_confirmation() RETURNS trigger AS $$
    DECLARE confirmed timestamptz;
    BEGIN
        SELECT m.confirmed_at INTO confirmed
          FROM intake_manifest m WHERE m.manifest_id = OLD.manifest_id;
        IF confirmed IS NOT NULL THEN
            RAISE EXCEPTION
              'manifest % was confirmed at %; its files are the record of a read that has already '
              'been agreed to. Read the folder again to pick up a correction.',
              OLD.manifest_id, confirmed
              USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_intake_file_frozen
        BEFORE UPDATE ON intake_file
        FOR EACH ROW EXECUTE FUNCTION intake_file_frozen_after_confirmation();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS trg_intake_file_frozen ON intake_file;
    DROP FUNCTION IF EXISTS intake_file_frozen_after_confirmation();
    REVOKE UPDATE (resolved_student_id, status, resolution_basis, resolution_path, reason_code)
        ON intake_file FROM sip_app;
    REVOKE UPDATE (confirmed_at, confirmed_by) ON intake_manifest FROM sip_app;
    """)
    op.drop_index("ix_intake_manifest_unconfirmed", "intake_manifest")
    op.drop_constraint("ck_intake_manifest_confirmation_is_attributed", "intake_manifest")
    op.drop_column("intake_manifest", "confirmed_by")
    op.drop_column("intake_manifest", "confirmed_at")
