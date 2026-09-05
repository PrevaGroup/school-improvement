-- Scoring subsystem smoke test — does the release authority actually hold?
--
--   PGPASSWORD=$(gcloud secrets versions access latest --secret=sip-migrator-password) \
--   psql "host=127.0.0.1 dbname=sip user=sip_migrator" -f sql/20_scoring_smoketest.sql 1>&2
--
-- Companion to 10_rls_smoketest.sql, and the same idea: prove an invariant by ATTEMPTING the thing
-- that must fail. Creating a trigger successfully says nothing about whether it fires — every
-- function in 0008-0012 was created without error and none had ever been provoked.
--
-- Everything happens inside one transaction and is rolled back. Nothing persists, and it is safe to
-- run against a live database.

\set ON_ERROR_STOP on
\timing off
BEGIN;

CREATE OR REPLACE FUNCTION pg_temp.expect_fail(sql text, what text) RETURNS void AS $$
BEGIN
    BEGIN
        EXECUTE sql;
    EXCEPTION WHEN others THEN
        RAISE NOTICE 'PASS  % (blocked: %)', what, replace(SQLERRM, E'\n', ' ');
        RETURN;
    END;
    RAISE EXCEPTION 'FAIL  % — this was allowed and must not be', what;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION pg_temp.expect_ok(sql text, what text) RETURNS void AS $$
BEGIN
    EXECUTE sql;
    RAISE NOTICE 'PASS  %', what;
END;
$$ LANGUAGE plpgsql;

-- --------------------------------------------------------------------------- --
-- Fixtures. `public` already exists in dim_tenant.
-- --------------------------------------------------------------------------- --
INSERT INTO artifact (artifact_id, run_id, content_hash, state, tenant_id, visibility)
VALUES ('sm-art-1', 'sm-run', 'hash-1', 'unbound', 'public', 'public'),
       ('sm-art-2', 'sm-run', 'hash-2', 'bound',   'public', 'public');

INSERT INTO score_event (event_id, artifact_id, run_id, node_id, scorer_type, status,
                         level, idempotency_key, tenant_id, visibility)
VALUES ('sm-ev-1', 'sm-art-2', 'sm-run', 'ci', 'ai', 'scored', 3, 'sm-idem-1',
        'public', 'public');

-- --------------------------------------------------------------------------- --
-- 1. The release authority. The claim the whole product rests on.
-- --------------------------------------------------------------------------- --
SELECT set_config('app.actor_type', 'machine', true);

SELECT pg_temp.expect_fail(
  $$UPDATE artifact SET state='released' WHERE artifact_id='sm-art-2'$$,
  'a machine cannot release');

SELECT pg_temp.expect_fail(
  $$UPDATE artifact SET state='released' WHERE artifact_id='sm-art-1'$$,
  'unbound -> released is not a legal move at all');

SELECT pg_temp.expect_fail(
  $$UPDATE artifact SET state='in_review' WHERE artifact_id='sm-art-1'$$,
  'unbound -> in_review skips binding');

-- The machine may make machine moves.
SELECT pg_temp.expect_ok(
  $$UPDATE artifact SET state='scored' WHERE artifact_id='sm-art-2'$$,
  'a machine may score a bound artifact');

-- A teacher may make any legal move. An unset actor defaults to machine, so this is the only
-- way to reach `released` — which is the point.
SELECT set_config('app.actor_type', 'teacher', true);
SELECT set_config('app.actor_id', 'sm-teacher', true);

SELECT pg_temp.expect_ok(
  $$UPDATE artifact SET state='composed'  WHERE artifact_id='sm-art-2'$$,
  'teacher: scored -> composed');
SELECT pg_temp.expect_ok(
  $$UPDATE artifact SET state='in_review' WHERE artifact_id='sm-art-2'$$,
  'teacher: composed -> in_review');
SELECT pg_temp.expect_ok(
  $$UPDATE artifact SET state='released'  WHERE artifact_id='sm-art-2'$$,
  'teacher: in_review -> released');

SELECT pg_temp.expect_fail(
  $$UPDATE artifact SET state='in_review' WHERE artifact_id='sm-art-2'$$,
  'released is terminal — supersession is a new artifact, not a move backwards');

-- Every move was recorded, with the actor who made it.
DO $$
DECLARE n int; who text;
BEGIN
    SELECT count(*), max(actor_id) INTO n, who
      FROM artifact_state_transition
     WHERE artifact_id='sm-art-2' AND to_state='released';
    IF n = 1 AND who = 'sm-teacher' THEN
        RAISE NOTICE 'PASS  the release was recorded against sm-teacher';
    ELSE
        RAISE EXCEPTION 'FAIL  release audit: % rows, actor %', n, who;
    END IF;
END $$;

-- --------------------------------------------------------------------------- --
-- 2. Scores append; they never change.
-- --------------------------------------------------------------------------- --
SELECT pg_temp.expect_fail(
  $$UPDATE score_event SET level=4 WHERE event_id='sm-ev-1'$$,
  'a score cannot be edited — an override appends');
SELECT pg_temp.expect_fail(
  $$DELETE FROM score_event WHERE event_id='sm-ev-1'$$,
  'a score cannot be deleted');
SELECT pg_temp.expect_fail(
  $$INSERT INTO score_event (event_id, artifact_id, run_id, node_id, scorer_type, status,
                             level, idempotency_key, tenant_id, visibility)
    VALUES ('sm-ev-dup','sm-art-2','sm-run','ci','ai','scored',3,'sm-idem-1','public','public')$$,
  'a resumed run cannot double an observation');
SELECT pg_temp.expect_fail(
  $$INSERT INTO score_event (event_id, artifact_id, run_id, node_id, scorer_type, status,
                             level, idempotency_key, tenant_id, visibility)
    VALUES ('sm-ev-2','sm-art-2','sm-run','ev','ai','abstained',2,'sm-idem-2','public','public')$$,
  'an abstention cannot carry a level');

-- --------------------------------------------------------------------------- --
-- 3. Deletion marks the frames it invalidates, in the same transaction.
-- --------------------------------------------------------------------------- --
INSERT INTO estimation_frame (frame_id, frame_key, version, definition, definition_hash,
                              status, tenant_id, visibility)
VALUES ('sm-frame', 'sm', 1, '{"windows":["fall 2026"]}'::jsonb, 'deadbeef', 'active',
        'public', 'public');
INSERT INTO estimation_frame_member (frame_id, event_id, enters_calibration,
                                     tenant_id, visibility)
VALUES ('sm-frame', 'sm-ev-1', true, 'public', 'public');

UPDATE score_event SET student_id='sm-student' WHERE false;  -- no-op; the trigger blocks UPDATE
DO $$
BEGIN
    -- The event was inserted without a student_id, so give the tombstone something to match on by
    -- targeting the artifact instead — same code path, different subject_type.
    INSERT INTO measurement_deletion_tombstone
        (tombstone_id, subject_type, subject_id, reason, tenant_id, visibility)
    VALUES ('sm-tomb', 'artifact', 'sm-art-2', 'smoke test', 'public', 'public');
END $$;

DO $$
DECLARE st text; marked int;
BEGIN
    SELECT status INTO st FROM estimation_frame WHERE frame_id='sm-frame';
    SELECT frames_marked_stale INTO marked
      FROM measurement_deletion_tombstone WHERE tombstone_id='sm-tomb';
    IF st = 'stale' AND marked = 1 THEN
        RAISE NOTICE 'PASS  a tombstone marked the frame stale in the same transaction (% frame)',
                     marked;
    ELSE
        RAISE EXCEPTION 'FAIL  frame status %, frames_marked_stale % — GET DIAGNOSTICS or the '
                        'join is wrong', st, marked;
    END IF;
END $$;

SELECT pg_temp.expect_fail(
  $$UPDATE estimation_frame SET definition='{"windows":["spring 2027"]}'::jsonb
     WHERE frame_id='sm-frame'$$,
  'an active frame definition is frozen');

-- --------------------------------------------------------------------------- --
-- 4. Registry identity.
-- --------------------------------------------------------------------------- --
INSERT INTO registry_node (node_id, standard_code, criterion_label, grade_band,
                           scale_categories, kind)
VALUES ('sm-node', 'RH.11-12.6', 'point of view', '11-12', '[1,2,3,4]'::jsonb, 'anchor');

SELECT pg_temp.expect_fail(
  $$INSERT INTO registry_node (node_id, standard_code, criterion_label, grade_band,
                               scale_categories, kind)
    VALUES ('sm-node-2','RI.11-12.6','x','11-12','[3]'::jsonb,'anchor')$$,
  'a one-category scale is not fittable');

SELECT pg_temp.expect_fail(
  $$UPDATE registry_node SET scale_categories='[1,2,3]'::jsonb WHERE node_id='sm-node'$$,
  'a node scale is its identity and cannot change');

INSERT INTO registry_node_version (node_version_id, node_id, version, descriptors, status)
VALUES ('sm-nv', 'sm-node', 1, '{"1":"a","2":"b","3":"c","4":"d"}'::jsonb, 'published');
SELECT pg_temp.expect_fail(
  $$UPDATE registry_node_version SET descriptors='{"1":"changed"}'::jsonb
     WHERE node_version_id='sm-nv'$$,
  'published descriptors are frozen');

-- --------------------------------------------------------------------------- --
-- 5. Section access fails closed.
-- --------------------------------------------------------------------------- --
DO $$
DECLARE n int;
BEGIN
    PERFORM set_config('app.principal_hash', '', true);
    SELECT count(*) INTO n FROM roster_visible_sections();
    IF n = 0 THEN
        RAISE NOTICE 'PASS  an unset principal sees no sections';
    ELSE
        RAISE EXCEPTION 'FAIL  unset principal saw % sections', n;
    END IF;
END $$;

ROLLBACK;
\echo ''
\echo 'All checks passed. Rolled back — nothing persisted.'
