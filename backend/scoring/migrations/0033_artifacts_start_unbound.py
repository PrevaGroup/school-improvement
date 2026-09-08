"""an artifact is created `unbound`, unless it is a corpus paper

Found while binding corpus papers. The transition trigger from 0008 is `BEFORE UPDATE`, so it
governs how an artifact MOVES and says nothing about how one arrives. Any code could insert an
artifact already `released` and skip the teacher check, the state history, and every guard the
state machine exists to provide — and nothing would be wrong afterwards, because no transition
ever happened to audit.

That is a hole in the release authority, not a corpus problem. It is closed here.

## Why corpus papers are the exception

A student's paper starts `unbound` because the system does not yet know whose it is; a teacher
resolves that, and the resolution is the decision the trigger protects. A corpus paper has no such
period: PERSUADE states the binding, there is no teacher, and there is no ambiguity for one to
resolve. Writing it `unbound` and then moving it would fabricate a decision nobody made — and the
only way to make that move legal would be to claim a teacher actor, which is worse.

So corpus papers are created `bound`, and how they got there is recorded in `resolution_path`
(every part `declared`, with the corpus id as the basis) rather than in a transition row. That is
the honest record: no decision happened, so there is nothing to attribute.

## Why the exception is a tenant and not a flag

Same reasoning as 0032. A parameter saying "trust me" is one somebody passes from the wrong place;
a tenant is checked by the database and the console cannot see it either way.

Revision ID: 0033
Revises: 0032
"""
from __future__ import annotations

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION scoring_check_artifact_birth() RETURNS trigger AS $$
    BEGIN
        IF NEW.state = 'unbound' THEN
            RETURN NEW;
        END IF;
        -- Reference corpora only. A corpus paper's binding is stated by the corpus, so it has no
        -- unbound period and no decision to attribute; see 0032.
        IF NEW.tenant_id = 'corpus' AND NEW.state = 'bound' THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
          'an artifact is created `unbound` and moves by transition; % was inserted directly as '
          '`%`, which would skip the teacher check and leave no state history.',
          NEW.artifact_id, NEW.state
          USING ERRCODE = 'check_violation';
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_artifact_birth
        BEFORE INSERT ON artifact
        FOR EACH ROW EXECUTE FUNCTION scoring_check_artifact_birth();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_artifact_birth ON artifact;")
    op.execute("DROP FUNCTION IF EXISTS scoring_check_artifact_birth();")
