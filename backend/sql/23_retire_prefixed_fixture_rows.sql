-- One-off: remove the `demo-` prefixed fixture rows that predate migration 0019.
--
--   PGPASSWORD=$(gcloud secrets versions access latest --secret=sip-migrator-password) \
--     psql "host=127.0.0.1 dbname=sip user=sip_migrator" -f sql/23_retire_prefixed_fixture_rows.sql 1>&2
--
-- WHY A FILE RATHER THAN THE PURGE. `registry.seed_demo --purge` was rewritten to walk the rubric
-- graph — `WHERE rubric_id = ...` — because identifiers stopped carrying a lifecycle prefix. That
-- column arrives in 0019. And 0019 also adds a CHECK requiring node_id to be a UUID, which the old
-- `demo-ci` rows violate, so they have to go BEFORE the upgrade.
--
-- Which makes the ordering impossible: the new purge needs the schema it is supposed to run ahead
-- of. Cleanup code that evolves with the schema cannot clean up the state that predates it, and
-- teaching it to straddle both shapes would leave a permanent branch in the code for a one-time
-- event. So this is that one-time event, written down instead of pasted into a terminal.
--
-- Safe to run when there is nothing to remove: every statement is a DELETE with a predicate, and
-- the counts come back zero.

\set ON_ERROR_STOP on
BEGIN;

-- THE ARTIFACTS FIRST, and this half was missing on the first pass. `scoring.seed_demo --purge`
-- reported `"artifact": 0` and that was read as "already gone" — it actually meant the rewritten
-- purge was scoped to run `fixture-run-1`, which did not exist yet, while the old rows belonged to
-- `demo-run-1`. A zero from a scoped delete means nothing matched the scope, not that nothing
-- exists, and the difference put four papers in a queue that should have held two.
--
-- score_event and artifact_composition are append-only by trigger, so the triggers come off for
-- this transaction. ALTER TABLE is transactional, so a failure rolls the disable back with
-- everything else.
ALTER TABLE score_event DISABLE TRIGGER trg_score_event_append_only;
ALTER TABLE artifact_composition DISABLE TRIGGER trg_artifact_composition_append_only;

DELETE FROM artifact_composition
      WHERE artifact_id IN (SELECT artifact_id FROM artifact WHERE run_id LIKE 'demo-%');
DELETE FROM score_event WHERE run_id LIKE 'demo-%';
DELETE FROM artifact_state_transition
      WHERE artifact_id IN (SELECT artifact_id FROM artifact WHERE run_id LIKE 'demo-%');
DELETE FROM artifact WHERE run_id LIKE 'demo-%';

ALTER TABLE score_event ENABLE TRIGGER trg_score_event_append_only;
ALTER TABLE artifact_composition ENABLE TRIGGER trg_artifact_composition_append_only;

-- Then the registry. score_event.node_id has no foreign key (it is a stamp, not a reference), so a
-- score written against a retired fixture node would keep its stamp — correct, because the event
-- records what was true when it was scored.
DELETE FROM registry_scoring_site_node WHERE site_id LIKE 'demo-%';
DELETE FROM registry_scoring_site      WHERE site_id LIKE 'demo-%';
DELETE FROM registry_task              WHERE task_id LIKE 'demo-%';
DELETE FROM registry_lint_acknowledgment
      WHERE subject LIKE 'demo-%' OR split_part(subject, ':', 1) LIKE 'demo-%';
DELETE FROM registry_node_version      WHERE node_id LIKE 'demo-%';
DELETE FROM registry_node              WHERE node_id LIKE 'demo-%';
DELETE FROM registry_scoring_configuration WHERE config_id LIKE 'demo-%';

\echo ''
\echo 'What is left with a demo- prefix (should be zero rows):'
SELECT 'artifact' AS t, count(*) FROM artifact WHERE run_id LIKE 'demo-%'
UNION ALL SELECT 'score_event', count(*) FROM score_event WHERE run_id LIKE 'demo-%'
UNION ALL SELECT 'registry_node', count(*) FROM registry_node WHERE node_id LIKE 'demo-%'
UNION ALL SELECT 'registry_node_version', count(*) FROM registry_node_version
    WHERE node_id LIKE 'demo-%'
UNION ALL SELECT 'registry_scoring_site', count(*) FROM registry_scoring_site
    WHERE site_id LIKE 'demo-%'
UNION ALL SELECT 'registry_task', count(*) FROM registry_task WHERE task_id LIKE 'demo-%'
UNION ALL SELECT 'registry_scoring_configuration', count(*) FROM registry_scoring_configuration
    WHERE config_id LIKE 'demo-%';

COMMIT;
\echo ''
\echo 'Done. `alembic upgrade head` will now accept 0019.'
