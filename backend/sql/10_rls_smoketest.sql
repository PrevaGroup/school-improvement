-- ============================================================================
-- 10_rls_smoketest.sql — prove tenant isolation on the star schema.
-- Run AFTER `alembic upgrade head`, as sip_migrator (owner):
--   sipsql -f sql/10_rls_smoketest.sql
-- (sip_migrator must be able to SET ROLE sip_app: GRANT sip_app TO sip_migrator;)
-- ============================================================================

-- ---- reference (no RLS) ----
INSERT INTO dim_tenant (tenant_id, tenant_type, display_name, jurisdiction) VALUES
  ('lbusd','district','Long Beach USD','CA'),
  ('fresno','district','Fresno USD','CA')
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO tenant_scope (tenant_id, school_id) VALUES
  ('lbusd','LB001'), ('fresno','FR001')
ON CONFLICT DO NOTHING;

INSERT INTO dim_school (school_id, school_name, district_id) VALUES
  ('LB001','LB Example School','lbusd'),
  ('FR001','Fresno Example School','fresno')
ON CONFLICT (school_id) DO NOTHING;

INSERT INTO dim_metric (metric_id, domain, display_name, data_origin) VALUES
  ('chronic_absenteeism_rate','attendance','Chronic Absenteeism','state'),
  ('belonging_pct','climate','Belonging','local_survey')
ON CONFLICT (metric_id) DO NOTHING;

INSERT INTO dim_student_group (student_group_id, label, dimension)
VALUES ('all','All Students','total') ON CONFLICT DO NOTHING;

-- dim_period is RLS'd (tenant-scoped); seed the standard annual period as public
SET app.tenant = 'public';
INSERT INTO dim_period (period_id, grain, school_year, label, tenant_id, visibility)
VALUES ('p2023-24','annual','2023-24','2023-24','public','public')
ON CONFLICT (period_id) DO NOTHING;

-- ---- facts (owner is subject to FORCE RLS -> set the tenant per insert) ----
SET app.tenant = 'public';
INSERT INTO fact_metric (school_id,period_id,metric_id,student_group_id,tenant_id,visibility,value,value_status)
VALUES ('LB001','p2023-24','chronic_absenteeism_rate','all','public','public',22.5,'reported')
ON CONFLICT DO NOTHING;

SET app.tenant = 'lbusd';
INSERT INTO fact_metric (school_id,period_id,metric_id,student_group_id,tenant_id,visibility,value,value_status)
VALUES ('LB001','p2023-24','belonging_pct','all','lbusd','private',71,'reported')
ON CONFLICT DO NOTHING;

SET app.tenant = 'fresno';
INSERT INTO fact_metric (school_id,period_id,metric_id,student_group_id,tenant_id,visibility,value,value_status)
VALUES ('FR001','p2023-24','belonging_pct','all','fresno','private',66,'reported')
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

SET app.tenant = '';
\echo '--- no tenant: expect ONLY the public chronic row ---'
SELECT tenant_id, visibility, metric_id, value FROM fact_metric ORDER BY metric_id;

-- ======================= WRITE ISOLATION ====================================
SET app.tenant = 'lbusd';
\echo '--- lbusd writing about a FRESNO school (not in its tenant_scope): expect rejection ---'
DO $$ BEGIN
  INSERT INTO fact_metric (school_id,period_id,metric_id,student_group_id,tenant_id,visibility,value,value_status)
  VALUES ('FR001','p2023-24','belonging_pct','all','lbusd','private',1,'reported');
  RAISE EXCEPTION 'FAIL: cross-school write was allowed';
EXCEPTION WHEN insufficient_privilege OR check_violation THEN
  RAISE NOTICE 'PASS: cross-school write rejected';
END $$;

\echo '--- lbusd writing a row owned by FRESNO: expect rejection ---'
DO $$ BEGIN
  INSERT INTO fact_metric (school_id,period_id,metric_id,student_group_id,tenant_id,visibility,value,value_status)
  VALUES ('LB001','p2023-24','belonging_pct','all','fresno','private',1,'reported');
  RAISE EXCEPTION 'FAIL: cross-tenant write was allowed';
EXCEPTION WHEN insufficient_privilege OR check_violation THEN
  RAISE NOTICE 'PASS: cross-tenant write rejected';
END $$;

RESET ROLE;
RESET app.tenant;
