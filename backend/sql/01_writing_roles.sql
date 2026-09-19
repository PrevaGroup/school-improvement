-- ============================================================================
-- 01_writing_roles.sql
-- Run ONCE as the Cloud SQL admin (the `postgres` user), after 00_bootstrap.sql and BEFORE
-- `alembic upgrade` reaches 0042. Alembic runs as sip_migrator, which cannot CREATE ROLE.
--
--   psql "host=127.0.0.1 user=postgres dbname=sip" -f sql/01_writing_roles.sql
--
-- Replace CHANGE_ME_writing_app with the value you store in Secret Manager as
-- `writing-app-password`. Grants on tables are NOT here: migration 0042 issues them, table by
-- table, so they are versioned with the schema they describe.
-- ============================================================================

-- The writing product's API role. Same posture as sip_app: not a superuser, not an owner,
-- NOBYPASSRLS — the row-level policies on student work apply to it.
CREATE ROLE writing_app LOGIN PASSWORD 'CHANGE_ME_writing_app'
  NOSUPERUSER NOCREATEROLE NOBYPASSRLS;

-- Names resolve in `writing` only. A query that names a SIP table fails with "does not exist"
-- rather than finding it — and would be refused anyway, because this role holds no grant there.
ALTER ROLE writing_app SET search_path = writing;

-- The one job that crosses into SIP's fact_metric. NOLOGIN until that job exists: give it LOGIN
-- and a password in the same change that ships the job.
CREATE ROLE writing_bridge NOLOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
ALTER ROLE writing_bridge SET search_path = writing, public;

GRANT CONNECT ON DATABASE sip TO writing_app;
GRANT CONNECT ON DATABASE sip TO writing_bridge;

-- sip_migrator issues the grants in 0042 as owner, which needs no membership. Membership is for
-- the smoke tests, which SET ROLE to prove what each role can and cannot see.
GRANT writing_app    TO sip_migrator;
GRANT writing_bridge TO sip_migrator;
