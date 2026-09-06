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

-- Children first. score_event.node_id has no foreign key (it is a stamp, not a reference), so a
-- score written against a retired fixture node keeps its stamp — which is correct: the event
-- records what was true when it was scored. Those rows were already removed with their artifacts.
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
SELECT 'registry_node' AS t, count(*) FROM registry_node WHERE node_id LIKE 'demo-%'
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
