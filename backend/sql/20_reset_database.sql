-- ============================================================================
-- 20_reset_database.sql
-- Drop & recreate the application database for a clean, from-scratch reload.
--
-- Roles (sip_migrator / sip_app) are cluster-level and created ONCE by
-- 00_bootstrap.sql; they persist across a database drop. This script therefore
-- re-creates only the DATABASE and its in-database grants — a repeatable teardown
-- for proving the full chain (schema -> seed -> load) builds from nothing.
--
-- Run as `postgres`, connected to a database OTHER than sip (DROP DATABASE can't
-- run while connected to its target), with the Cloud SQL Auth Proxy up:
--   psql "host=127.0.0.1 user=postgres dbname=postgres" -f sql/20_reset_database.sql
-- Then:  alembic upgrade head   &&   re-run the loaders.
-- ============================================================================

-- WITH (FORCE) terminates other sessions on sip (Postgres 13+) so the drop succeeds.
DROP DATABASE IF EXISTS sip WITH (FORCE);
CREATE DATABASE sip OWNER sip_migrator;

\connect sip

GRANT CONNECT ON DATABASE sip TO sip_app;
GRANT USAGE   ON SCHEMA public TO sip_app;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT  CREATE ON SCHEMA public TO sip_migrator;

ALTER DEFAULT PRIVILEGES FOR ROLE sip_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sip_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sip_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO sip_app;
