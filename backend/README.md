# School Improvement Platform — API (FastAPI + SQLAlchemy + Alembic)

Multi-tenant backend for the CA school-improvement data. Public/state data is shared;
each district's own data (Panorama survey, local SIS, SPSA extraction) is isolated by
**Postgres row-level security**, enforced at the row — not in application code.

Implements the model in [`../California/docs/TARGET_SCHEMA.md`](../California/docs/TARGET_SCHEMA.md) §10.

## Checklist → where it lives

| Item | Where |
|---|---|
| Create the application **database** | [`sql/00_bootstrap.sql`](sql/00_bootstrap.sql) — `CREATE DATABASE sip` |
| **App role**, NOT superuser / NOT owner; migrate as a separate role | bootstrap creates `sip_app` (runtime) + `sip_migrator` (owns objects, runs Alembic); app uses `DATABASE_URL`, Alembic uses `MIGRATION_DATABASE_URL` |
| **Schema split**: public/reference vs private tenant (every row has `tenant_id`) | [`app/models/reference.py`](app/models/reference.py) vs [`app/models/tenant.py`](app/models/tenant.py) |
| **`ENABLE` + `FORCE ROW LEVEL SECURITY`** on every private table | [`migrations/versions/0001_initial_schema.py`](migrations/versions/0001_initial_schema.py) |
| **RLS policies** scoped via a per-request **session variable** | migration 0001 (`app.tenant`) + [`app/db.py`](app/db.py) (`SET LOCAL`) |
| **Alembic** from day one | `alembic.ini`, `migrations/` |

## Why the app role must not own the tables (FERPA)

Student data is FERPA-protected; even aggregate cells can re-identify at small N. RLS is
the guardrail that stops one district's query from ever returning another's rows. But two
Postgres roles *bypass* RLS: **superusers** and **table owners**. So the runtime role
(`sip_app`) is deliberately **neither** — non-superuser, non-owner, `NOBYPASSRLS` — and
every private table is set to **`FORCE ROW LEVEL SECURITY`** so even the owner is subject to
policy. That combination is what makes "RLS is on" actually mean "RLS is enforced."

## Setup

```bash
# 0. Tunnel Cloud SQL to localhost (or use the Python Connector — see app/db.py)
cloud-sql-proxy PROJECT:REGION:INSTANCE --port 5432

# 1. Roles + database (run ONCE as the Cloud SQL admin `postgres`)
psql "host=127.0.0.1 user=postgres" -f sql/00_bootstrap.sql

# 2. Python deps
python -m venv .venv && . .venv/Scripts/activate    # Windows; use bin/activate on *nix
pip install -r requirements.txt

# 3. Config
cp .env.example .env    # set the two DB URLs + DEV_MODE=true for local

# 4. Migrate (runs as sip_migrator via MIGRATION_DATABASE_URL)
alembic upgrade head

# 5. Prove isolation works
psql "host=127.0.0.1 dbname=sip user=sip_migrator" -f sql/10_rls_smoketest.sql
#    (needs: GRANT sip_app TO sip_migrator;  so it can SET ROLE for the test)

# 6. Run the API
uvicorn app.main:app --reload
```

Try it: `GET /schools?year=2023-24` (public), and `GET /schools/{cds}/metrics?year=2023-24`
with header `X-Dev-Tenant: lbusd` vs `fresno` — the private rows change, the public ones don't.

## Design notes

- **Tenant binding is the trust boundary** (§10.3). The client never sends `tenant_id`;
  [`app/security.py`](app/security.py) resolves it from a *verified* Google ID token (wire up
  `_verify_google_id_token` before prod), and [`app/db.py`](app/db.py) binds it with
  `SET LOCAL app.tenant` inside the request transaction (resets on commit → pool-safe).
- **Typed endpoints only.** The API composes queries; callers pass parameters. Because the
  model never emits raw SQL, the session-variable binding is safe. If you ever expose a raw-SQL
  tool to an LLM, switch that path to per-tenant DB roles + read-only (§10.3, pattern 2).
- **Public reference is shared** (`dim_*`, `ref_benchmark`) — no RLS, granted `SELECT` to the
  app role. `fact_metric`/plan tables hold public rows (`tenant_id='public'`) *and* private
  rows in one table; the read policy `visibility='public' OR tenant_id = <me>` handles the mix.
- **The ETL/public loader** runs as `sip_migrator` with `SET app.tenant='public'` (Cloud SQL has
  no true superuser, so don't rely on `BYPASSRLS`).
- **Scope of this scaffold:** a vertical slice (5 reference + 4 private tables). Add the rest of
  the schema as new models + `alembic revision --autogenerate` migrations; the RLS pattern in
  0001 is the template for any new private table.
