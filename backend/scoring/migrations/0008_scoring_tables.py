"""scoring tables — the writing subsystem's record: artifact, score_event, state transitions

Three tables plus the state machine, enforced in the database.

The trigger is the point of this migration. "Only a teacher may transition an artifact to
released" is the authority claim the whole product rests on, and a rule of that weight enforced in
the interface is a rule someone can be persuaded to relax in a sprint planning meeting. Here an
illegal transition raises, whoever attempts it and from whatever code path.

score_event is append-only: an UPDATE or DELETE raises. Overrides append a row referencing the one
they disagree with, which is what keeps the pairing (this configuration said 3, this named teacher
said 2) intact as a calibration observation.

TENANCY: artifact and score_event carry tenant_id + visibility but RLS is NOT enabled here. Turning
it on is a deliberate core move made when the subsystem first holds real student writing — the same
posture 0006 took for the eval tables, and for the same reason: the policy flip should be a
reviewed decision, not a side effect of a module appearing.

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Mirrors scoring/models.py ARTIFACT_TRANSITIONS. Duplicated deliberately: a migration must be
# readable and runnable at the revision it was written, without importing code that has since
# moved. backend/scoring/tests/test_state_machine.py asserts the two agree.
_TRANSITIONS = {
    "unbound":      {"bound": "teacher", "withheld": "teacher"},
    "bound":        {"scored": "machine", "not_scorable": "machine", "withheld": "teacher"},
    "not_scorable": {"bound": "teacher", "withheld": "teacher"},
    "scored":       {"composed": "machine", "withheld": "teacher"},
    "composed":     {"in_review": "machine", "blocked": "machine", "withheld": "teacher"},
    "blocked":      {"in_review": "teacher", "withheld": "teacher"},
    "in_review":    {"released": "teacher", "withheld": "teacher"},
    "released":     {},
    "withheld":     {},
}
_STATES = sorted(_TRANSITIONS)


def _transition_sql() -> str:
    """Build the VALUES list the trigger checks against, from the map above."""
    rows = ",\n        ".join(
        f"('{frm}','{to}','{actor}')"
        for frm, moves in _TRANSITIONS.items()
        for to, actor in moves.items())
    return rows


def upgrade() -> None:
    states = sa.Enum(*_STATES, name="artifact_state_enum", create_type=False)

    op.create_table(
        "artifact",
        sa.Column("artifact_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text()),
        sa.Column("section_id", sa.Text()),
        sa.Column("task_id", sa.Text()),
        sa.Column("iteration", sa.Text()),
        sa.Column("window_label", sa.Text()),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("source_uri", sa.Text()),
        sa.Column("handed_in_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("resolution_path", postgresql.JSONB()),
        sa.Column("state", sa.Text(), nullable=False, server_default="unbound"),
        sa.Column("state_reason_code", sa.Text()),
        sa.Column("superseded_by_artifact_id", sa.Text(),
                  sa.ForeignKey("artifact.artifact_id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.CheckConstraint(
            "state IN (" + ",".join(f"'{s}'" for s in _STATES) + ")",
            name="state"),
    )
    op.create_index("ix_artifact_binding", "artifact",
                    ["tenant_id", "section_id", "task_id", "iteration"])
    op.create_index("ix_artifact_student", "artifact", ["tenant_id", "student_id"])
    op.create_index("ix_artifact_run", "artifact", ["run_id"])
    op.create_index("ix_artifact_state", "artifact", ["tenant_id", "state"])

    op.create_table(
        "score_event",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("artifact_id", sa.Text(), sa.ForeignKey("artifact.artifact_id"),
                  nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text()),
        sa.Column("section_id", sa.Text()),
        sa.Column("task_id", sa.Text()),
        sa.Column("iteration", sa.Text()),
        sa.Column("window_label", sa.Text()),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("trait_set_version", sa.Text()),
        sa.Column("rubric_version", sa.Text()),
        sa.Column("form_variant", sa.Text()),
        sa.Column("scoring_configuration_id", sa.Text()),
        sa.Column("scorer_type", sa.Text(), nullable=False),
        sa.Column("scorer_id", sa.Text()),
        sa.Column("human_blind", sa.Boolean()),
        sa.Column("scrutiny_passes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("escalation_trigger", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("level", sa.Numeric()),
        sa.Column("confidence", sa.Text()),
        sa.Column("reason", sa.Text()),
        sa.Column("reason_code", sa.Text()),
        sa.Column("evidence", postgresql.JSONB()),
        sa.Column("is_measurement_occasion", sa.Boolean()),
        sa.Column("enters_calibration", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revised_after_feedback", sa.Boolean()),
        sa.Column("supersedes_event_id", sa.Text(), sa.ForeignKey("score_event.event_id")),
        sa.Column("set_override_id", sa.Text()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.UniqueConstraint("idempotency_key", name="uq_score_event_idempotency"),
        sa.CheckConstraint("scorer_type IN ('ai','teacher','expert')",
                           name="scorer_type"),
        # A level without a score, or a score without a level, is a row that means nothing.
        sa.CheckConstraint(
            "(status = 'scored' AND level IS NOT NULL) OR "
            "(status <> 'scored' AND level IS NULL)",
            name="level_matches_status"),
    )
    op.create_index("ix_score_event_artifact", "score_event", ["artifact_id"])
    op.create_index("ix_score_event_node", "score_event", ["tenant_id", "node_id"])
    op.create_index("ix_score_event_binding", "score_event",
                    ["tenant_id", "section_id", "task_id", "iteration"])
    op.create_index("ix_score_event_calibration", "score_event",
                    ["tenant_id", "enters_calibration"])
    op.create_index("ix_score_event_config", "score_event", ["scoring_configuration_id"])

    op.create_table(
        "artifact_state_transition",
        sa.Column("transition_id", sa.Text(), primary_key=True),
        sa.Column("artifact_id", sa.Text(), sa.ForeignKey("artifact.artifact_id"),
                  nullable=False),
        sa.Column("from_state", sa.Text()),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text()),
        sa.Column("reason_code", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("dim_tenant.tenant_id"),
                  nullable=False, server_default="public"),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="public"),
        sa.CheckConstraint("actor_type IN ('machine','teacher')",
                           name="actor_type"),
    )
    op.create_index("ix_artifact_state_transition_artifact", "artifact_state_transition",
                    ["artifact_id", "created_at"])

    # ----------------------------------------------------------------------- #
    # The state machine, in the database.
    #
    # The actor is read from `app.actor_type`, set with SET LOCAL alongside app.tenant — the same
    # mechanism the tenancy seam already uses, so the pipeline cannot claim to be a teacher by
    # passing a different argument. Unset means machine: a code path that forgot to say who it is
    # cannot release.
    # ----------------------------------------------------------------------- #
    op.execute(f"""
    CREATE TABLE artifact_transition_rule (
        from_state text NOT NULL,
        to_state   text NOT NULL,
        actor_type text NOT NULL,
        PRIMARY KEY (from_state, to_state)
    );
    INSERT INTO artifact_transition_rule (from_state, to_state, actor_type) VALUES
        {_transition_sql()};

    CREATE FUNCTION scoring_check_artifact_transition() RETURNS trigger AS $$
    DECLARE
        required_actor text;
        actor          text := coalesce(nullif(current_setting('app.actor_type', true), ''),
                                        'machine');
    BEGIN
        IF NEW.state IS NOT DISTINCT FROM OLD.state THEN
            RETURN NEW;
        END IF;

        SELECT r.actor_type INTO required_actor
          FROM artifact_transition_rule r
         WHERE r.from_state = OLD.state AND r.to_state = NEW.state;

        IF required_actor IS NULL THEN
            RAISE EXCEPTION
              'illegal artifact transition: % -> % (artifact %)',
              OLD.state, NEW.state, OLD.artifact_id
              USING ERRCODE = 'check_violation';
        END IF;

        -- A teacher may make any legal move; a machine may make only machine moves. This is the
        -- release authority, and it is the reason the trigger exists.
        IF required_actor = 'teacher' AND actor <> 'teacher' THEN
            RAISE EXCEPTION
              'transition % -> % requires a teacher, actor was % (artifact %)',
              OLD.state, NEW.state, actor, OLD.artifact_id
              USING ERRCODE = 'insufficient_privilege';
        END IF;

        INSERT INTO artifact_state_transition
            (transition_id, artifact_id, from_state, to_state, actor_type, actor_id,
             tenant_id, visibility)
        VALUES
            (gen_random_uuid()::text, OLD.artifact_id, OLD.state, NEW.state, actor,
             nullif(current_setting('app.actor_id', true), ''),
             OLD.tenant_id, OLD.visibility);

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_artifact_transition
        BEFORE UPDATE ON artifact
        FOR EACH ROW EXECUTE FUNCTION scoring_check_artifact_transition();

    -- score_event is append-only. An override appends; nothing edits.
    CREATE FUNCTION scoring_score_event_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION
          'score_event is append-only: % rejected. An override writes a new event referencing the prior one.',
          TG_OP
          USING ERRCODE = 'check_violation';
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_score_event_append_only
        BEFORE UPDATE OR DELETE ON score_event
        FOR EACH ROW EXECUTE FUNCTION scoring_score_event_append_only();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS trg_score_event_append_only ON score_event;
    DROP FUNCTION IF EXISTS scoring_score_event_append_only();
    DROP TRIGGER IF EXISTS trg_artifact_transition ON artifact;
    DROP FUNCTION IF EXISTS scoring_check_artifact_transition();
    DROP TABLE IF EXISTS artifact_transition_rule;
    """)
    op.drop_table("artifact_state_transition")
    op.drop_table("score_event")
    op.drop_table("artifact")
