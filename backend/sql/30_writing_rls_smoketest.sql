-- ============================================================================
-- 30_writing_rls_smoketest.sql — prove that student work is scoped to classes, and that the
-- two products cannot read each other's tables.
-- Run AFTER `alembic upgrade head`, as sip_migrator (owner), on a NON-production database:
--   psql ... -v ON_ERROR_STOP=1 -f sql/30_writing_rls_smoketest.sql
-- (sip_migrator must be able to SET ROLE to sip_app, writing_app and writing_bridge — the
--  bootstrap and 01_writing_roles.sql grant that.)
--
-- Everything runs in one transaction and ends in ROLLBACK, so it leaves nothing behind. Any
-- failed expectation raises and stops the script; reaching the final NOTICE means every check
-- passed.
--
-- Two districts, three classes, three teachers, one teacher whose assignment has ended:
--   smoke_a  section smoke-a1  teacher A1   (+ an expired co-teacher)
--            section smoke-a2  teacher A2
--   smoke_b  section smoke-b1  teacher B1
-- ============================================================================
\set ON_ERROR_STOP 1
BEGIN;

-- ---- seed, as owner (migration 0041 ENABLEs rather than FORCEs, so the owner is unbound) ----
INSERT INTO dim_tenant (tenant_id, tenant_type, display_name, jurisdiction) VALUES
  ('smoke_a', 'district', 'Smoke District A', 'CA'),
  ('smoke_b', 'district', 'Smoke District B', 'CA');

INSERT INTO roster_section (section_id, name, tenant_id, visibility) VALUES
  ('smoke-a1', 'A1', 'smoke_a', 'private'),
  ('smoke-a2', 'A2', 'smoke_a', 'private'),
  ('smoke-b1', 'B1', 'smoke_b', 'private');

INSERT INTO roster_student (student_id, display_name, tenant_id, visibility) VALUES
  ('stu-a1', 'Student in A1', 'smoke_a', 'private'),
  ('stu-a2', 'Student in A2', 'smoke_a', 'private'),
  ('stu-b1', 'Student in B1', 'smoke_b', 'private');

INSERT INTO roster_enrollment (enrollment_id, section_id, student_id, tenant_id, visibility) VALUES
  ('enr-a1', 'smoke-a1', 'stu-a1', 'smoke_a', 'private'),
  ('enr-a2', 'smoke-a2', 'stu-a2', 'smoke_a', 'private'),
  ('enr-b1', 'smoke-b1', 'stu-b1', 'smoke_b', 'private');

INSERT INTO roster_section_staff (section_staff_id, section_id, principal_hash, role,
                                  active_from, active_to, tenant_id, visibility) VALUES
  ('st-a1',  'smoke-a1', 'hash-A1',  'teacher',    NULL, NULL, 'smoke_a', 'private'),
  ('st-a2',  'smoke-a2', 'hash-A2',  'teacher',    NULL, NULL, 'smoke_a', 'private'),
  ('st-b1',  'smoke-b1', 'hash-B1',  'teacher',    NULL, NULL, 'smoke_b', 'private'),
  ('st-old', 'smoke-a1', 'hash-OLD', 'co_teacher', '2020-01-01', '2020-06-30', 'smoke_a', 'private');

INSERT INTO artifact (artifact_id, run_id, student_id, section_id, content_hash, state,
                      tenant_id, visibility) VALUES
  ('art-a1', 'run-smoke', 'stu-a1', 'smoke-a1', 'h1', 'unbound', 'smoke_a', 'private'),
  ('art-a2', 'run-smoke', 'stu-a2', 'smoke-a2', 'h2', 'unbound', 'smoke_a', 'private'),
  ('art-b1', 'run-smoke', 'stu-b1', 'smoke-b1', 'h3', 'unbound', 'smoke_b', 'private');

INSERT INTO score_event (event_id, artifact_id, run_id, node_id, scorer_type, status,
                         idempotency_key, tenant_id, visibility) VALUES
  ('ev-a1', 'art-a1', 'run-smoke', 'n1', 'ai', 'abstained', 'k-a1', 'smoke_a', 'private'),
  ('ev-a2', 'art-a2', 'run-smoke', 'n1', 'ai', 'abstained', 'k-a2', 'smoke_a', 'private'),
  ('ev-b1', 'art-b1', 'run-smoke', 'n1', 'ai', 'abstained', 'k-b1', 'smoke_b', 'private');

INSERT INTO intake_manifest (manifest_id, source_kind, source_ref, declared_section_id,
                             tenant_id, visibility) VALUES
  ('man-a1', 'local', 'folder-a1', 'smoke-a1', 'smoke_a', 'private'),
  ('man-a2', 'local', 'folder-a2', 'smoke-a2', 'smoke_a', 'private');

INSERT INTO intake_file (file_id, manifest_id, source_ref, name, status, tenant_id, visibility) VALUES
  ('file-a1', 'man-a1', 'f1', 'a1.docx', 'unresolved', 'smoke_a', 'private'),
  ('file-a2', 'man-a2', 'f2', 'a2.docx', 'unresolved', 'smoke_a', 'private');

-- ---- the checks, as the API role ----
CREATE FUNCTION pg_temp.expect(label text, got bigint, want bigint) RETURNS void AS $$
BEGIN
    IF got IS DISTINCT FROM want THEN
        RAISE EXCEPTION 'FAILED: % — got %, want %', label, got, want;
    END IF;
END $$ LANGUAGE plpgsql;

CREATE FUNCTION pg_temp.as_caller(principal text, tenant text) RETURNS void AS $$
    SELECT set_config('app.principal_hash', coalesce(principal, ''), true),
           set_config('app.tenant', coalesce(tenant, ''), true);
$$ LANGUAGE sql;

CREATE FUNCTION pg_temp.expect_refused(label text, probe text) RETURNS void AS $$
BEGIN
    BEGIN
        EXECUTE probe;
    EXCEPTION WHEN insufficient_privilege OR undefined_table THEN
        RETURN;  -- refused, or not even nameable: both correct
    END;
    RAISE EXCEPTION 'FAILED: % — the query ran', label;
END $$ LANGUAGE plpgsql;

INSERT INTO pooling_aggregation_consent (consent_id, district_tenant_id, scope, effective_from)
VALUES ('consent-a', 'smoke_a', 'module_evidence', current_date - 1),
       ('consent-b-other-scope', 'smoke_b', 'teacher_instrumentation', current_date - 1);

-- 0. The products cannot reach each other's tables at all, whatever the settings say.
SET LOCAL ROLE sip_app;
SELECT pg_temp.as_caller('hash-A1', 'smoke_a');
SELECT pg_temp.expect_refused('sip_app reads student work',  'SELECT 1 FROM writing.artifact');
SELECT pg_temp.expect_refused('sip_app reads the roster',    'SELECT 1 FROM writing.roster_student');
RESET ROLE;
SET LOCAL ROLE writing_app;
SELECT pg_temp.expect_refused('writing_app reads SIP metrics', 'SELECT 1 FROM public.fact_metric');
SELECT pg_temp.expect_refused('writing_app reads SIP plans',   'SELECT 1 FROM public.plan');
SELECT pg_temp.expect_refused('writing_app reads tenants',     'SELECT 1 FROM public.dim_tenant');

-- 1. Nobody bound: nothing at all, including the staff table that authorises everything else.
SELECT pg_temp.as_caller(NULL, NULL);
SELECT pg_temp.expect('unbound caller: artifacts',   (SELECT count(*) FROM artifact), 0);
SELECT pg_temp.expect('unbound caller: students',    (SELECT count(*) FROM roster_student), 0);
SELECT pg_temp.expect('unbound caller: staff rows',  (SELECT count(*) FROM roster_section_staff), 0);
SELECT pg_temp.expect('unbound caller: score events',(SELECT count(*) FROM score_event), 0);

-- 2. Teacher A1 sees their class and nothing else — not the other class in their own district.
SELECT pg_temp.as_caller('hash-A1', 'smoke_a');
SELECT pg_temp.expect('A1: own staff rows only',     (SELECT count(*) FROM roster_section_staff), 1);
SELECT pg_temp.expect('A1: sections',                (SELECT count(*) FROM roster_section), 1);
SELECT pg_temp.expect('A1: students',                (SELECT count(*) FROM roster_student), 1);
SELECT pg_temp.expect('A1: artifacts',               (SELECT count(*) FROM artifact), 1);
SELECT pg_temp.expect('A1: artifact is theirs',
       (SELECT count(*) FROM artifact WHERE artifact_id = 'art-a1'), 1);
SELECT pg_temp.expect('A1: score events',            (SELECT count(*) FROM score_event), 1);
SELECT pg_temp.expect('A1: manifests',               (SELECT count(*) FROM intake_manifest), 1);
SELECT pg_temp.expect('A1: files',                   (SELECT count(*) FROM intake_file), 1);

-- 3. A forged district does not help: the tenant must match AND the section must be theirs.
SELECT pg_temp.as_caller('hash-A1', 'smoke_b');
SELECT pg_temp.expect('A1 claiming B: artifacts',    (SELECT count(*) FROM artifact), 0);
SELECT pg_temp.expect('A1 claiming B: students',     (SELECT count(*) FROM roster_student), 0);

-- 4. Writes outside the class affect nothing or are refused.
SELECT pg_temp.as_caller('hash-A1', 'smoke_a');
WITH u AS (UPDATE artifact SET state_reason_code = 'smoke' WHERE artifact_id = 'art-a2' RETURNING 1)
SELECT pg_temp.expect('A1: update another class''s artifact', (SELECT count(*) FROM u), 0);
WITH u AS (UPDATE artifact SET state_reason_code = 'smoke' WHERE artifact_id = 'art-a1' RETURNING 1)
SELECT pg_temp.expect('A1: update own artifact',     (SELECT count(*) FROM u), 1);
-- Moving a paper out of the class, or scoring someone else's, must RAISE rather than no-op.
DO $$
BEGIN
    BEGIN
        UPDATE artifact SET section_id = 'smoke-a2' WHERE artifact_id = 'art-a1';
        RAISE EXCEPTION 'FAILED: A1 moved their artifact into another class';
    EXCEPTION WHEN insufficient_privilege THEN NULL;  -- new row violates the policy: correct
    END;
    BEGIN
        INSERT INTO score_event (event_id, artifact_id, run_id, node_id, scorer_type, status,
                                 idempotency_key, tenant_id, visibility)
        VALUES ('ev-forged', 'art-a2', 'run-smoke', 'n1', 'teacher', 'abstained', 'k-forged',
                'smoke_a', 'private');
        RAISE EXCEPTION 'FAILED: A1 wrote a score onto another class''s paper';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;
INSERT INTO score_event (event_id, artifact_id, run_id, node_id, scorer_type, status,
                         idempotency_key, tenant_id, visibility)
VALUES ('ev-own', 'art-a1', 'run-smoke', 'n1', 'teacher', 'abstained', 'k-own', 'smoke_a', 'private');
SELECT pg_temp.expect('A1: score on own paper',
       (SELECT count(*) FROM score_event WHERE event_id = 'ev-own'), 1);

-- 5. No DELETE policy and no DELETE grant: even their own rows cannot be deleted by the API.
SELECT pg_temp.expect_refused('A1: delete transitions', 'DELETE FROM artifact_state_transition');
SELECT pg_temp.expect_refused('A1: delete enrollments', 'DELETE FROM roster_enrollment');
SELECT pg_temp.expect_refused('A1: write the roster',
       $q$INSERT INTO roster_section_staff (section_staff_id, section_id, principal_hash, role,
          tenant_id, visibility) VALUES ('forged', 'smoke-a2', 'hash-A1', 'teacher', 'smoke_a',
          'private')$q$);

-- 6. The tables the API never touches are closed to it outright.
SELECT pg_temp.expect_refused('A1: drive connections', 'SELECT 1 FROM intake_drive_connection');
SELECT pg_temp.expect_refused('A1: estimation frames', 'SELECT 1 FROM estimation_frame');
SELECT pg_temp.expect_refused('A1: the corpus',        'SELECT 1 FROM corpus_paper');

-- 7. An assignment that has ended grants nothing, though the row is still there.
SELECT pg_temp.as_caller('hash-OLD', 'smoke_a');
SELECT pg_temp.expect('expired co-teacher: artifacts', (SELECT count(*) FROM artifact), 0);

-- 8. The other district's teacher, symmetrically.
SELECT pg_temp.as_caller('hash-B1', 'smoke_b');
SELECT pg_temp.expect('B1: artifacts',               (SELECT count(*) FROM artifact), 1);
SELECT pg_temp.expect('B1: sees none of A',
       (SELECT count(*) FROM artifact WHERE tenant_id = 'smoke_a'), 0);

-- 9. The bridge: a district's scores only while its module-evidence consent stands, and
--    nothing that names a student or a class.
RESET ROLE;
SET LOCAL ROLE writing_bridge;
SELECT pg_temp.as_caller(NULL, 'smoke_a');
SELECT pg_temp.expect('bridge, consented district: score events', (SELECT count(*) FROM score_event), 3);  -- both classes, incl. check 4's
SELECT pg_temp.as_caller(NULL, 'smoke_b');
SELECT pg_temp.expect('bridge, wrong-scope consent: score events', (SELECT count(*) FROM score_event), 0);
SELECT pg_temp.expect_refused('bridge reads the roster', 'SELECT 1 FROM roster_student');
SELECT pg_temp.expect_refused('bridge reads the papers', 'SELECT 1 FROM artifact_composition');
RESET ROLE;
UPDATE pooling_aggregation_consent SET revoked_at = now() WHERE consent_id = 'consent-a';
SET LOCAL ROLE writing_bridge;
SELECT pg_temp.as_caller(NULL, 'smoke_a');
SELECT pg_temp.expect('bridge, revoked consent: score events', (SELECT count(*) FROM score_event), 0);

-- 10. The owner — what the batch jobs run as — is not bound by any of this.
RESET ROLE;
SELECT pg_temp.expect('owner: artifacts', (SELECT count(*) FROM artifact
                                            WHERE run_id = 'run-smoke'), 3);

DO $$ BEGIN RAISE NOTICE 'writing RLS smoke test: every check passed'; END $$;
ROLLBACK;
