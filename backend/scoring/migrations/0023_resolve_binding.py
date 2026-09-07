"""scoring — a teacher may say whose an unbound paper is, and may not change their mind later

Resolving a stuck file means setting `artifact.student_id`, which 0018 deliberately did not grant:
`GRANT UPDATE (state, state_reason_code)` was chosen precisely so a request handler could never
reassign whose work a set of scores describes.

That reasoning still holds — it just does not hold for an artifact that has no student yet. A file
nobody could be matched to sits in `unbound` with `student_id IS NULL`, and a teacher naming the
author is the one legitimate way that column gets filled.

So the grant widens by one column and a trigger draws the line the grant cannot: `student_id` may
be set while the artifact is `unbound`, and may never change afterwards. A column grant cannot say
"only from NULL, only in this state"; a trigger can, and this is the same division of labour the
release authority already uses — the interface proposes and the database decides.

WHY REBINDING IS REFUSED RATHER THAN AUDITED. By the time an artifact leaves `unbound` it may
carry scores, a review, a released message and a delivery record, all of which describe a specific
student's writing. Pointing that history at a different person does not correct a mistake, it
manufactures a false record for two people at once. A mis-resolved paper is fixed by withholding
it and binding the file again, which leaves both facts in the record.

Revision ID: 0023
Revises: 0022
"""
from __future__ import annotations

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

APP_ROLE = "sip_app"


def upgrade() -> None:
    op.execute(f"GRANT UPDATE (student_id) ON artifact TO {APP_ROLE};")
    op.execute("""
    CREATE FUNCTION scoring_check_rebind() RETURNS trigger AS $$
    BEGIN
        IF NEW.student_id IS DISTINCT FROM OLD.student_id THEN
            IF OLD.student_id IS NOT NULL THEN
                RAISE EXCEPTION
                  'artifact % is already bound to %; a paper cannot be reassigned. Withhold it '
                  'and bind the file again, which leaves both facts in the record.',
                  OLD.artifact_id, OLD.student_id
                  USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.state <> 'unbound' THEN
                RAISE EXCEPTION
                  'artifact % is in state %, not unbound — a student may only be named while '
                  'nobody has been named yet.', OLD.artifact_id, OLD.state
                  USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    -- BEFORE the transition trigger fires alphabetically after this one, which does not matter:
    -- both are BEFORE UPDATE and neither depends on the other's outcome. What matters is that a
    -- statement setting student_id AND state at once is checked by both.
    CREATE TRIGGER trg_artifact_rebind
        BEFORE UPDATE ON artifact
        FOR EACH ROW EXECUTE FUNCTION scoring_check_rebind();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS trg_artifact_rebind ON artifact;
    DROP FUNCTION IF EXISTS scoring_check_rebind();
    """)
    op.execute(f"REVOKE UPDATE (student_id) ON artifact FROM {APP_ROLE};")
