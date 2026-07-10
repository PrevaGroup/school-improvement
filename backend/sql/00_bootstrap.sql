-- ============================================================================
-- 00_bootstrap.sql
-- Run ONCE as the Cloud SQL admin (the `postgres` user) against the INSTANCE.
-- Creates cluster-level roles + the application database. Alembic cannot do this
-- (it connects INTO the database as the migrator role, and can't CREATE ROLE /
-- CREATE DATABASE for itself).
--
--   psql "host=127.0.0.1 user=postgres" -f sql/00_bootstrap.sql
--   (with the Cloud SQL Auth Proxy tunneling the instance to 127.0.0.1:5432)
-- ============================================================================

-- 1. Roles -------------------------------------------------------------------
-- migrator: owns schema objects and runs Alembic. Privileged, but NOT a superuser.
CREATE ROLE sip_migrator LOGIN PASSWORD 'CHANGE_ME_migrator'
  NOSUPERUSER NOCREATEROLE NOBYPASSRLS;

-- app: the role the API runtime connects as.
--   NOT a superuser, NOT the table owner, NOBYPASSRLS  ->  this is what makes RLS
--   actually enforce. (Superusers and BYPASSRLS roles skip policies; table OWNERS
--   skip them too unless FORCE ROW LEVEL SECURITY is set — which migration 0001 does.)
CREATE ROLE sip_app LOGIN PASSWORD 'CHANGE_ME_app'
  NOSUPERUSER NOCREATEROLE NOBYPASSRLS;

-- 2. Database ----------------------------------------------------------------
-- Cloud SQL note: the `postgres` admin is NOT a true superuser (only
-- cloudsqlsuperuser), so to CREATE a database OWNED BY sip_migrator it must first
-- be a MEMBER of sip_migrator. We also let sip_migrator manage sip_app, which the
-- RLS smoke test needs (it does SET ROLE sip_app).
GRANT sip_migrator TO postgres;
GRANT sip_app TO sip_migrator;
CREATE DATABASE sip OWNER sip_migrator;

-- 3. In-database grants ------------------------------------------------------
\connect sip

GRANT CONNECT ON DATABASE sip TO sip_app;
GRANT USAGE   ON SCHEMA public TO sip_app;

-- Only the migrator creates objects in the public schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT  CREATE ON SCHEMA public TO sip_migrator;

-- Anything the migrator creates later is automatically DML-accessible to the app
-- (table-level grants are ALSO issued explicitly in migration 0001; this covers
--  future tables so you don't have to remember).
ALTER DEFAULT PRIVILEGES FOR ROLE sip_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sip_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sip_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO sip_app;

-- ----------------------------------------------------------------------------
-- Cloud SQL note (FERPA-relevant): you are NOT a real superuser (only
-- `cloudsqlsuperuser`), so BYPASSRLS may be ungrantable. The ETL / public-data
-- loader therefore runs as sip_migrator (the table OWNER). On the FORCE-RLS
-- private tables the owner is *also* subject to policy, so the loader must do
--     SET app.tenant = 'public';
-- before inserting public rows (their tenant_id is 'public', so the write policy
-- passes and the school-scope LIKE resolves to '%'). Reference/public tables have
-- no RLS, so seeding those needs no tenant context.
-- ----------------------------------------------------------------------------
