# Architecture — School Improvement Platform

A multi-tenant data platform for California school-improvement analysis. **Public** state
data (attendance, behavior, academics, …) is shared across everyone; a **district's own**
data (its improvement plans, and later its private metrics) is isolated by PostgreSQL
row-level security. This document is the map: how the pieces fit, where they live in the
repo, and what's left to build.

**Stack:** Cloud SQL (Postgres) · Cloud Run (FastAPI) · React + Vite on Cloudflare Pages ·
Google Cloud Identity Platform (GCIP) · Cloud Storage + Claude for raw-data / plan ingest.

**Guiding principle:** this is a *prototype*. Build the isolation seam (`tenant_id` + RLS)
correctly now because it's expensive to retrofit; keep everything else simple and upgrade
later.

---

## 1. How a request flows (the trust boundary)

The whole security model hinges on one seam: **the tenant is derived from a verified
identity server-side, never sent by the client.** Postgres then enforces it.

```mermaid
flowchart LR
    U[Browser<br/>React + Vite] -->|1. sign in| G[GCIP<br/>identity]
    G -->|2. ID token JWT| U
    U -->|3. Bearer token| API[FastAPI on Cloud Run]
    API -->|4. verify_firebase_token| G
    API -->|5. SET LOCAL app.tenant = tenant| DB[(Cloud SQL Postgres<br/>Row-Level Security)]
    DB -->|6. only public + this tenant's rows| API
    API --> U
```

1. The user signs in through **GCIP** — email/password, the district's SSO (SAML/OIDC), or
   a social provider. **No Gmail required**; GCIP is a customer-identity service.
2. GCIP returns a signed **ID token** (a Firebase/Identity-Platform JWT).
3. The browser calls the API with `Authorization: Bearer <token>`.
4. [`app/security.py`](backend/app/security.py) **verifies** the token — signature, issuer
   (`securetoken.google.com/<project>`), audience (the project id), expiry — using
   `google-auth`'s `verify_firebase_token`. Then it maps the verified identity to a
   `tenant_id` (a **custom claim** on the user, or an email-domain fallback).
5. [`app/db.py`](backend/app/db.py) opens a session and runs `SET LOCAL app.tenant = <tenant>`.
6. The **RLS policies** ([migration 0001](backend/migrations/versions/0001_initial_schema.py))
   scope every private table to `tenant_id = current_setting('app.tenant')`. The app connects
   as `sip_app` — a **non-owner, NOBYPASSRLS** role — so the database enforces isolation even
   if application code has a bug.

That is the only real glue in the stack. Everything else is conventional.

## 2. The data model (five layers)

Full spec: [`docs/TARGET_SCHEMA.md`](docs/TARGET_SCHEMA.md). Generated table reference:
[`backend/SCHEMA_REFERENCE.md`](backend/SCHEMA_REFERENCE.md). The model is dimensional (a
star schema) organised as five conceptual layers:

| Layer | What it holds | Where |
|---|---|---|
| **raw** | Source files as pulled from CDE / data.ca.gov | Cloud Storage (`gs://…/raw/ca/…`), not in repo |
| **staging** | The reviewable shape between "what a loader read" and "what the DB believes" | e.g. the SIP `ExtractedPlan` JSON ([schema.py](backend/etl/ca/sip/schema.py)) |
| **star** | Conformed facts + dimensions — the keystone `fact_metric` (grain: school × period × metric × student-group) plus `dim_*` | [`app/models/`](backend/app/models/), 17 tables |
| **augment** | Plans and other tenant entities that *reference* the star (`plan` / `plan_goal` / `plan_action`) | [`app/models/tenant.py`](backend/app/models/tenant.py) |
| **marts** | Semantic read models for the dashboard / agents | not built yet |

**Identity** keys on the federal **NCES** id; the California **CDS** code rides alongside as
`state_school_id` / `state_district_id`. A CDS→NCES crosswalk runs in every loader, with a
`CA-<cds>` fallback for schools without an NCES id yet.

## 3. Two ingest pipelines

**A. Public metrics (bulk ETL).** Per-fact loaders read CDE files and write `fact_metric`
rows at `tenant_id='public'`. Thin scripts over shared machinery — see
[`backend/etl/ca/`](backend/etl/ca/) and [its README](backend/etl/ca/README.md). Run in
Cloud Shell against Cloud SQL via the Auth Proxy.

**B. School improvement plans (PDF → review → DB).** The one that turns a district's SPSA/
LCAP PDF into structured, private, tenant-scoped data:

```
PDF ──▶ POST /plans/extract ──▶ ExtractedPlan JSON ──▶ human review ──▶ POST /plans/load ──▶ plan_* tables
        (Claude reads the PDF,   (goals, actions,        (confirm the      (writes only under
         schema.py contract)      metric-link proposals,  proposed metric    the caller's tenant,
                                  page-level provenance)   mappings)          RLS-enforced)
```

- Extractor core: [`backend/etl/ca/sip/extract_sip.py`](backend/etl/ca/sip/extract_sip.py)
  (Claude Opus 4.8 reads the PDF natively; Python stamps deterministic ids + source hash).
- API surface: [`backend/app/plans.py`](backend/app/plans.py) — `extract` (returns the review
  JSON, writes nothing) and `load` (approved JSON → DB).
- Loader: [`backend/app/plan_loader.py`](backend/app/plan_loader.py) — only *confirmed*
  metric links are written; idempotent via deterministic ids.

## 4. Deployment

Container + Cloud Run steps: [`backend/DEPLOY.md`](backend/DEPLOY.md). The API uses the Cloud
SQL Python Connector when `INSTANCE_CONNECTION_NAME` is set (no Auth-Proxy sidecar on Cloud
Run), else the proxy URL locally. Secrets (`sip-app-password`, `sip-migrator-password`,
`anthropic-api-key`) come from Secret Manager via ADC — never the repo.

---

## Repository index

| Path | What it is |
|---|---|
| [`README.md`](README.md) | One-paragraph overview + status |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | **This document** |
| [`docs/TARGET_SCHEMA.md`](docs/TARGET_SCHEMA.md) | The data-model spec — five layers, tenancy + RLS, missingness, instruments |
| [`docs/DATA_CATALOG.md`](docs/DATA_CATALOG.md) | Raw CA data sources and how they were obtained |
| **Backend** | |
| [`backend/README.md`](backend/README.md) | Roles/bootstrap, migrations, RLS smoke test, running loaders |
| [`backend/DEPLOY.md`](backend/DEPLOY.md) | Cloud Run deploy: Dockerfile, Cloud SQL Connector, secrets |
| [`backend/SCHEMA_REFERENCE.md`](backend/SCHEMA_REFERENCE.md) | Generated table reference (from the models) |
| [`backend/app/config.py`](backend/app/config.py) | Settings; secrets from Secret Manager (DB + Anthropic) |
| [`backend/app/db.py`](backend/app/db.py) | Engine + tenant-bound session (`SET LOCAL app.tenant`) |
| [`backend/app/security.py`](backend/app/security.py) | **The trust boundary** — verify GCIP token → tenant |
| [`backend/app/main.py`](backend/app/main.py) | FastAPI app + routes (`/health`, `/schools`, plans router) |
| [`backend/app/plans.py`](backend/app/plans.py) | `POST /plans/extract` + `POST /plans/load` |
| [`backend/app/plan_loader.py`](backend/app/plan_loader.py) | Approved plan JSON → `plan`/`plan_goal`/`plan_action` |
| [`backend/app/models/`](backend/app/models/) | SQLAlchemy models — `base` (RLS table lists), `reference` (public), `tenant` (private) |
| [`backend/migrations/`](backend/migrations/) | Alembic — `0001` (schema + RLS), `0002` (NCES re-key) |
| [`backend/sql/`](backend/sql/) | `00_bootstrap` (roles/DB), `10_rls_smoketest`, `20_reset_database` |
| **ETL** | |
| [`backend/etl/ca/`](backend/etl/ca/) | Public-data loaders `load_ca_<fact>.py` + [README](backend/etl/ca/README.md) + `_shared.py` (conformed vocab) |
| [`backend/etl/ca/sip/`](backend/etl/ca/sip/) | SIP extractor: `schema.py` (contract), `extract_sip.py` (runner), `example_extract.json` |

Repo: **github.com/PrevaGroup/school-improvement** (branch `main`).

---

## Status

- **Live:** Cloud SQL Postgres, full aggregate **star schema (17 tables)** + **RLS** (tenant
  isolation proven), credentials in Secret Manager. **8 public metrics loaded** (~960k
  `fact_metric` rows).
- **Built, not yet deployed:** the FastAPI app, the SIP extract/load pipeline, GCIP token
  verification, the Cloud Run Dockerfile + Connector wiring.
- **Not done:** user provisioning, the marts layer, the frontend, a real Cloud Run deploy.

## Remaining architecture tasks

**Auth / provisioning**
- [ ] Stand up GCIP user provisioning — create users and set the `tenant_id` custom claim
      (`firebase-admin` / Identity Platform Admin API). Until then, use `DOMAIN_TENANT_MAP`.
- [ ] Seed `dim_tenant` with the real districts; create a second tenant for isolation testing.

**Deploy**
- [ ] `gcloud run deploy` the backend (see `backend/DEPLOY.md`); create the `anthropic-api-key`
      secret; grant the runtime SA `secretAccessor` + `cloudsql.client`.
- [ ] Re-run the tenant-isolation test end-to-end against the deployed API (log in as two
      districts, confirm neither sees the other's plans).

**SIP pipeline**
- [ ] Run the extractor against a real Long Beach SPSA and eyeball the JSON vs. `schema.py`.
- [ ] Add a `bridge_action_metric` + provenance table (migration) so the load is lossless
      (multi-metric goals, page-level provenance) instead of one-metric-per-goal.
- [ ] Review UI/endpoint to move metric links `proposed → confirmed` before load; orphan
      pruning on re-load.

**Data / marts**
- [ ] Build the benchmarking derive (state/district/peer, status×change bands) — deferred
      rollup rows go to `ref_benchmark`.
- [ ] Build the **marts** semantic layer the dashboard/agents read.

**Frontend**
- [ ] Scaffold React + Vite; integrate the GCIP client SDK; wire to the API; deploy on
      Cloudflare Pages.

---

## Cost at MVP scale (rough, USD/mo)

| Item | Cost |
|---|---|
| Cloud SQL (small, single-zone) | ~$10–25 |
| Cloud Run (FastAPI, min-instances = 0) | ~$0–5 |
| Cloudflare Pages | Free |
| Identity Platform (under free-tier MAU) | ~$0 |
| Cloud Storage (raw data, Standard, first 5 GB free) | pennies–$2 |
| Claude API (SIP extraction, per-plan) | usage-based |
| **Total (excl. Claude usage)** | **~$15–35/mo** |

## FERPA & access-control decisions (carry forward)

- **Isolation is enforced in the database**: app connects as a non-owner, NOBYPASSRLS role +
  `FORCE ROW LEVEL SECURITY`, so a code bug can't leak across tenants. Every private row
  carries a consistent `tenant_id` and no query joins across tenants — this keeps the option
  to peel a tenant into its own schema/DB when a real FERPA contract lands.
- **Access control = RLS only, flat within a district.** Every authenticated member of a
  district sees all of that district's data — no per-user roles in the MVP.
- **Tenant granularity = the district.** No school- or student-level access structure yet.
- **ReBAC + finer granularity + FERPA arrive together.** District-level aggregates are
  generally not FERPA-covered PII; the moment data gets granular enough to be FERPA-sensitive
  is the same moment you'd add relationship-based access control. Treat them as one future
  milestone, not three.
