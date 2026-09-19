"""the writing product gets its own schema and its own database user

Migration 0041 made student work readable only by the people who teach it. It did that inside one
grant space: `sip_app`, SIP's runtime role, still held table grants on every student table and was
kept out only by policy. This makes the boundary between the two products a privilege boundary as
well:

- Every writing table and function moves into schema `writing`.
- `sip_app` loses every grant on it and never had USAGE on the schema, so a SIP route cannot name a
  student table even by mistake.
- `writing_app` — the role the student-work routes now connect as — gets USAGE on `writing` and,
  table by table, exactly the commands 0041's policies allow. It has no grant on anything in
  `public`, so a writing route cannot read SIP's private tables either.
- `writing_bridge` — the one job meant to cross, feeding aggregates into `fact_metric` — gets read
  access to a district's score events only while that district's consent is in force (enforced by
  policy here, not by the job remembering to filter), and INSERT on `fact_metric`, under SIP's own
  FORCE policies. It is created NOLOGIN: the job does not exist yet, and a role that can log in
  before anything needs to is a credential waiting to be misused.

## The roles are created outside Alembic

Alembic connects as `sip_migrator`, which cannot CREATE ROLE (see `sql/00_bootstrap.sql`). Run
`sql/01_writing_roles.sql` as the Cloud SQL admin first; this migration refuses to run without the
two roles rather than failing halfway through the grants.

## Names still resolve unqualified

Every query in the codebase names tables bare. Rather than rewrite them all, the database's default
search_path becomes `public, writing`: batch jobs and migrations (as `sip_migrator`) see both,
`writing_app`'s role-level setting (from `01_writing_roles.sql`) is `writing` alone, and `sip_app`
has no USAGE on `writing`, so it resolves nothing there. Functions are moved and pinned to
`search_path = writing`, because a trigger body resolves its names when it runs, under the caller's
path, and a trigger that finds a different table depending on who fired it is not a trigger anyone
can reason about.

New writing tables after this migration must say `schema="writing"` in `op.create_table`;
`tests/test_writing_schema.py` holds that.

Revision ID: 0042
Revises: 0041
"""
from __future__ import annotations

import importlib.util
import pathlib

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

SCHEMA = "writing"
OLD_APP_ROLE = "sip_app"
APP_ROLE = "writing_app"
BRIDGE_ROLE = "writing_bridge"

# Every table the writing modules own. Order does not matter for SET SCHEMA; foreign keys, indexes,
# sequences, triggers and policies travel with their table.
TABLES: tuple[str, ...] = (
    # scoring
    "artifact", "score_event", "artifact_state_transition", "artifact_transition_rule",
    "artifact_composition",
    # intake, delivery
    "intake_manifest", "intake_file", "intake_drive_connection", "artifact_delivery",
    # measurement
    "estimation_frame", "estimation_frame_member", "measurement_deletion_tombstone",
    "measurement_fit_run", "measurement_fit_element",
    # roster
    "roster_student", "roster_section", "roster_enrollment", "roster_section_staff",
    # registry
    "registry_node", "registry_skill", "registry_rubric", "registry_rubric_trait",
    "registry_node_version", "registry_task", "registry_scoring_site", "registry_scoring_site_node",
    "registry_scoring_configuration", "registry_lint_acknowledgment",
    # corpus
    "corpus_source", "corpus_paper", "corpus_score", "corpus_discourse_span",
    # pooling
    "pooling_aggregation_consent", "pooling_aggregate_run",
)

FUNCTIONS: tuple[str, ...] = (
    "roster_visible_sections(text)",
    "scoring_check_artifact_transition()",
    "scoring_score_event_append_only()",
    "scoring_composition_append_only()",
    "scoring_check_rebind()",
    "scoring_check_artifact_birth()",
    "intake_file_frozen_after_confirmation()",
    "delivery_append_only()",
    "delivery_requires_release()",
    "measurement_freeze_active_frame()",
    "measurement_tombstone_marks_frames_stale()",
    "registry_freeze_published_version()",
    "registry_freeze_node_scale()",
)

# Reference content the API reads, and has no policy on because it is nobody's student work.
# `artifact_transition_rule` is read by the transition trigger, which runs as the caller.
APP_READS: tuple[str, ...] = ("registry_node", "registry_task", "artifact_transition_rule")

# The bridge's own bookkeeping, and the reference it needs to name what it aggregated.
BRIDGE_READS: tuple[str, ...] = ("pooling_aggregation_consent", "registry_node")
BRIDGE_WRITES: tuple[str, ...] = ("pooling_aggregate_run",)

# Consent gates ENTRY to the frame (writing/pooling/CONTRACT.md, rule 2): a district's rows are invisible
# to the bridge unless an unrevoked consent covers today. Enforced here so a job that forgets to
# filter computes over nothing rather than over data nobody agreed to share. Score events are
# module evidence; `teacher_instrumentation` consent does not admit them.
_CONSENTED = (
    "tenant_id = nullif(current_setting('app.tenant', true), '') AND EXISTS ("
    "SELECT 1 FROM pooling_aggregation_consent c"
    " WHERE c.district_tenant_id = tenant_id AND c.scope = 'module_evidence'"
    " AND c.revoked_at IS NULL"
    " AND c.effective_from <= current_date"
    " AND (c.effective_to IS NULL OR c.effective_to >= current_date))"
)
BRIDGE_POLICIES: tuple[str, ...] = ("score_event", "artifact")


def _load_0041():
    path = pathlib.Path(__file__).with_name("0041_writing_rls.py")
    spec = importlib.util.spec_from_file_location("m0041", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require_roles() -> None:
    op.execute(f"""
    DO $$
    DECLARE missing text;
    BEGIN
        SELECT string_agg(r, ', ') INTO missing
          FROM unnest(ARRAY['{APP_ROLE}', '{BRIDGE_ROLE}']) AS r
         WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r);
        IF missing IS NOT NULL THEN
            RAISE EXCEPTION 'roles % do not exist: run sql/01_writing_roles.sql as the Cloud SQL '
                            'admin before this migration', missing;
        END IF;
    END $$;
    """)


def _set_search_path(value: str) -> None:
    op.execute(f"""
    DO $$ BEGIN
        EXECUTE format('ALTER DATABASE %I SET search_path = {value}', current_database());
    END $$;
    """)
    # This session too, so the rest of this run — and every later migration in it — resolves the
    # same way a new connection will.
    op.execute(f"SET search_path = {value}")


def upgrade() -> None:
    _require_roles()
    m0041 = _load_0041()

    op.execute(f"CREATE SCHEMA {SCHEMA}")
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} SET SCHEMA {SCHEMA}")
    for fn in FUNCTIONS:
        op.execute(f"ALTER FUNCTION public.{fn} SET SCHEMA {SCHEMA}")
        op.execute(f"ALTER FUNCTION {SCHEMA}.{fn} SET search_path = {SCHEMA}")
    _set_search_path(f"public, {SCHEMA}")

    # SIP's role: nothing here, at any level.
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {OLD_APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM {OLD_APP_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {SCHEMA} FROM PUBLIC")

    # The writing API: the policies 0041 wrote now name it, and it holds exactly their commands.
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {SCHEMA} TO {APP_ROLE}")
    for table, (_predicate, commands) in m0041.POLICIES.items():
        op.execute(f"GRANT {', '.join(commands)} ON {SCHEMA}.{table} TO {APP_ROLE}")
        for command in commands:
            op.execute(f"ALTER POLICY {m0041._policy_name(command)} ON {SCHEMA}.{table} "
                       f"TO {APP_ROLE}")
    for table in APP_READS:
        op.execute(f"GRANT SELECT ON {SCHEMA}.{table} TO {APP_ROLE}")

    # The bridge.
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {BRIDGE_ROLE}")
    op.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {SCHEMA} TO {BRIDGE_ROLE}")
    for table in BRIDGE_POLICIES:
        op.execute(f"GRANT SELECT ON {SCHEMA}.{table} TO {BRIDGE_ROLE}")
        op.execute(f"CREATE POLICY p_bridge_select ON {SCHEMA}.{table} FOR SELECT "
                   f"TO {BRIDGE_ROLE} USING ({_CONSENTED})")
    for table in BRIDGE_READS:
        op.execute(f"GRANT SELECT ON {SCHEMA}.{table} TO {BRIDGE_ROLE}")
    for table in BRIDGE_WRITES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.{table} TO {BRIDGE_ROLE}")
    # SIP's side: insert only, and fact_metric's FORCE policies still bind it to one district's
    # schools at a time. Backward revocation (rule 3) will need a scoped way to retract what it
    # wrote; that is designed with the job, not granted in advance as DELETE on the whole table.
    op.execute(f"GRANT SELECT, INSERT ON public.fact_metric TO {BRIDGE_ROLE}")


def downgrade() -> None:
    m0041 = _load_0041()

    op.execute(f"REVOKE SELECT, INSERT ON public.fact_metric FROM {BRIDGE_ROLE}")
    for table in BRIDGE_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS p_bridge_select ON {SCHEMA}.{table}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {BRIDGE_ROLE}")
    op.execute(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {SCHEMA} FROM {BRIDGE_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM {BRIDGE_ROLE}")

    for table, (_predicate, commands) in m0041.POLICIES.items():
        for command in commands:
            op.execute(f"ALTER POLICY {m0041._policy_name(command)} ON {SCHEMA}.{table} "
                       f"TO {OLD_APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {SCHEMA} FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM {APP_ROLE}")

    for fn in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {SCHEMA}.{fn} RESET search_path")
        op.execute(f"ALTER FUNCTION {SCHEMA}.{fn} SET SCHEMA public")
    op.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO PUBLIC")
    for table in TABLES:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} SET SCHEMA public")
    # What sip_app held before: the bootstrap's default privileges gave it full DML on every table.
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{table} TO {OLD_APP_ROLE}")
    op.execute(f"DROP SCHEMA {SCHEMA}")
    op.execute("""
    DO $$ BEGIN
        EXECUTE format('ALTER DATABASE %I RESET search_path', current_database());
    END $$;
    """)
    op.execute("SET search_path = public")
