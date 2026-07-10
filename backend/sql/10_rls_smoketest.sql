-- ============================================================================
-- 10_rls_smoketest.sql — prove tenant isolation actually works.
-- Run AFTER `alembic upgrade head`, as sip_migrator (owner), e.g.:
--   psql "host=127.0.0.1 dbname=sip user=sip_migrator" -f sql/10_rls_smoketest.sql
-- The migrator must be able to SET ROLE sip_app: GRANT sip_app TO sip_migrator;
-- ============================================================================

-- ---- seed reference (public, no RLS) ----
INSERT INTO dim_tenant (tenant_id, tenant_type, display_name, cds_prefix) VALUES
  ('lbusd','district','Long Beach USD','1964725'),
  ('fresno','district','Fresno USD','1062166')
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO dim_student_group (student_group_id, label, dimension)
VALUES ('all','All Students','total') ON CONFLICT DO NOTHING;

INSERT INTO dim_metric (metric_id, domain, display_name, data_origin) VALUES
  ('chronic_absenteeism_rate','attendance','Chronic Absenteeism','state'),
  ('belonging_pct','climate','Belonging','local_survey')
ON CONFLICT (metric_id) DO NOTHING;

INSERT INTO dim_school (school_cds, school_year, school_name, district_cds) VALUES
  ('19647256019994','2023-24','LB Example School','1964725'),
  ('10621666019995','2023-24','Fresno Example School','1062166')
ON CONFLICT DO NOTHING;

-- ---- seed facts (owner is subject to FORCE RLS, so set the tenant per insert) ----
SET app.tenant = 'public';
INSERT INTO fact_metric (school_cds,school_year,metric_id,student_group_id,tenant_id,visibility,value,value_status)
VALUES ('19647256019994','2023-24','chronic_absenteeism_rate','all','public','public',22.5,'reported')
ON CONFLICT DO NOTHING;

SET app.tenant = 'lbusd';
INSERT INTO fact_metric (school_cds,school_year,metric_id,student_group_id,tenant_id,visibility,value,value_status)
VALUES ('19647256019994','2023-24','belonging_pct','all','lbusd','private',71,'reported')
ON CONFLICT DO NOTHING;

SET app.tenant = 'fresno';
INSERT INTO fact_metric (school_cds,school_year,metric_id,student_group_id,tenant_id,visibility,value,value_status)
VALUES ('10621666019995','2023-24','belonging_pct','all','fresno','private',66,'reported')
ON CONFLICT DO NOTHING;
RESET app.tenant;

-- ======================= READ ISOLATION (as the app role) ===================
SET ROLE sip_app;

SET app.tenant = 'lbusd';
\echo '--- as lbusd: expect chronic(public) + belonging(lbusd)=71, NOT fresno ---'
SELECT tenant_id, visibility, metric_id, value FROM fact_metric ORDER BY metric_id;

SET app.tenant = 'fresno';
\echo '--- as fresno: expect chronic(public) + belonging(fresno)=66, NOT lbusd ---'
SELECT tenant_id, visibility, metric_id, value FROM fact_metric ORDER BY metric_id;

SET app.tenant = '';   -- no/unknown tenant
\echo '--- no tenant: expect ONLY the public chronic row ---'
SELECT tenant_id, visibility, metric_id, value FROM fact_metric ORDER BY metric_id;

-- ======================= WRITE ISOLATION ====================================
SET app.tenant = 'lbusd';
\echo '--- lbusd writing about a FRESNO school: expect RLS violation ---'
DO $$ BEGIN
  INSERT INTO fact_metric (school_cds,school_year,metric_id,student_group_id,tenant_id,visibility,value,value_status)
  VALUES ('10621666019995','2023-24','belonging_pct','all','lbusd','private',1,'reported');
  RAISE EXCEPTION 'FAIL: cross-school write was allowed';
EXCEPTION WHEN insufficient_privilege OR check_violation THEN
  RAISE NOTICE 'PASS: cross-school write rejected';
END $$;

\echo '--- lbusd writing a row owned by FRESNO: expect RLS violation ---'
DO $$ BEGIN
  INSERT INTO fact_metric (school_cds,school_year,metric_id,student_group_id,tenant_id,visibility,value,value_status)
  VALUES ('19647256019994','2023-24','belonging_pct','all','fresno','private',1,'reported');
  RAISE EXCEPTION 'FAIL: cross-tenant write was allowed';
EXCEPTION WHEN insufficient_privilege OR check_violation THEN
  RAISE NOTICE 'PASS: cross-tenant write rejected';
END $$;

RESET ROLE;
RESET app.tenant;
-- Cleanup (optional): DELETE the seeded rows, or just DROP/recreate a scratch DB.
