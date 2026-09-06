"""scoring — let the API role read the record and make a teacher's moves

Every table in 0008 and 0017 was created by the migrator and granted to nobody, which is correct
for a pipeline that only ever ran as a batch job. The review console changes that: `sip_app` now
has to read the queue and write the two things a teacher does.

THE UPDATE GRANT IS COLUMN-LEVEL, and that is the point of this migration rather than an
afterthought. `GRANT UPDATE ON artifact` would let the API rewrite `student_id`, `task_id` or
`content_hash` — silently reassigning whose work a set of scores describes. The teacher's action is
"move this artifact to a new state", so the grant is exactly `(state, state_reason_code)` and
nothing else. A bug in a request handler cannot become a re-binding.

`score_event` gets INSERT and nothing else: an override APPENDS. UPDATE and DELETE are refused by
trigger anyway, but a grant that says so as well means two independent things have to fail before
a score can be edited.

`artifact_state_transition` needs INSERT because the transition trigger writes the audit row as the
CALLING role — it is not SECURITY DEFINER, deliberately, so the audit row is written by whoever
made the move rather than by an ambient privileged identity.

`artifact_composition` is SELECT only. Composing is a batch job; the API reads packets and does not
make them.

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

APP_ROLE = "sip_app"


def upgrade() -> None:
    op.execute(f"""
    GRANT SELECT ON artifact, score_event, artifact_state_transition, artifact_composition
        TO {APP_ROLE};

    -- The teacher's moves, and only those.
    GRANT UPDATE (state, state_reason_code) ON artifact TO {APP_ROLE};
    GRANT INSERT ON score_event TO {APP_ROLE};
    GRANT INSERT ON artifact_state_transition TO {APP_ROLE};
    """)


def downgrade() -> None:
    op.execute(f"""
    REVOKE INSERT ON artifact_state_transition FROM {APP_ROLE};
    REVOKE INSERT ON score_event FROM {APP_ROLE};
    REVOKE UPDATE (state, state_reason_code) ON artifact FROM {APP_ROLE};
    REVOKE SELECT ON artifact, score_event, artifact_state_transition, artifact_composition
        FROM {APP_ROLE};
    """)
