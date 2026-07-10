# MVP Setup Runbook — School Data Prototype

**Stack:** Cloud SQL (Postgres) · Cloud Run (FastAPI) · React + Vite on Cloudflare Pages · Google Cloud Identity Platform · Cloud Storage for raw data

**Guiding principle:** This is a *prototype*. Build the isolation seam (tenant_id + RLS) correctly now because it's expensive to retrofit; keep everything else as simple as possible and upgrade later.

---

## Phase 0 — Accounts & foundations

- [X] Created a dedicated **GCP project** called school-improvement under prevagroup.com.
- [X] Enable **billing** on the project and set a **budget alert** (e.g., email at $50 and $100/mo) so nothing surprises you.
- [X] Created github.com/PrevaGroup/school-improvement (`/frontend` and `/backend` isn't created).
- [X] Create a **Cloudflare account** for Pages (if you don't have one).
- [X] Decided on a **domain** (`sip.prevagroup.com` for the frontend, `api.sip.prevagroup.com` for the backend (same-domain setup avoids CORS headaches later).
- [X] Enable required GCP APIs: Cloud SQL Admin, Cloud Run, Identity Platform, Secret Manager, Cloud Storage.

## Phase 1 — Database (Cloud SQL + RLS)  ← do this carefully

- [X ] Provision **Cloud SQL for PostgreSQL**, smallest instance, **single-zone** (no HA — that's a later toggle).
- [ ] Create the application **database**.
- [ ] Create a **dedicated app role** that is **NOT a superuser and NOT the table owner** (this is what makes RLS actually enforce — see FERPA note below). Run migrations as a separate, more-privileged role.
- [ ] Design the **schema** with the split we discussed:
  - Public / reference tables (the mostly-public data) — shared, read by everyone.
  - Private tenant tables — every row carries a **`tenant_id`** (org) column.
- [ ] Turn on **`ENABLE ROW LEVEL SECURITY`** *and* **`FORCE ROW LEVEL SECURITY`** on every private table.
- [ ] Write **RLS policies** that scope private rows to the current tenant (via a session variable set per request).
- [ ] Set up a **migrations tool** — **Alembic** (pairs with SQLAlchemy/FastAPI) so schema changes are versioned from day one.

## Phase 2 — Auth (Google Cloud Identity Platform)

- [ ] Enable **Identity Platform** and configure sign-in providers (email/password to start; add "Sign in with Google" social if you want it).
- [ ] In the FastAPI backend, **verify the GCIP JWT** on every request.
- [ ] Build the **auth → RLS bridge**: map the authenticated user to their org, and **set the Postgres tenant session variable per request** so RLS applies. (This is the one real piece of glue in the whole stack — test it deliberately.)

## Phase 3 — Backend (FastAPI on Cloud Run)

- [ ] Scaffold the **FastAPI** app; add a **Dockerfile**.
- [ ] Connect to Cloud SQL using the built-in **Cloud SQL connector / Auth Proxy**.
- [ ] Add a **connection pool** and set a **modest `max-instances`** on Cloud Run so serverless scale-out can't exhaust Postgres connections.
- [ ] Store secrets (DB creds, etc.) in **Secret Manager** — never in code or the repo.
- [ ] Deploy to **Cloud Run**. For MVP set **`min-instances = 0`** (accept the occasional cold start; it's free). Revisit only if cold starts bug you.

## Phase 4 — Frontend (React + Vite on Cloudflare Pages)

- [ ] Scaffold the **React + Vite** app.
- [ ] Integrate the **Identity Platform client SDK** for login/signup.
- [ ] Point the app at the **API base URL**; configure **CORS** (or put both behind one domain).
- [ ] Connect the GitHub repo to **Cloudflare Pages** for automatic deploys on push.

## Phase 5 — Raw data & population

- [ ] Create a **Cloud Storage bucket** for raw source data (public datasets, CSVs, dumps).
- [ ] Upload the raw data to the bucket.
- [ ] Write a **Python loader/ETL script**: read from the bucket → clean/transform → load into Cloud SQL.
- [ ] **Seed the public/reference tables** with the public data.
- [ ] Create **one sample tenant** with a little sample private data — you need at least two tenants to test isolation.

## Phase 6 — Verify & guardrails

- [ ] **Tenant-isolation test (critical):** log in as Org A and Org B and confirm neither can see the other's private rows. This is the test that matters most for the FERPA trajectory.
- [ ] Confirm the app connects as the **non-owner app role** (so `FORCE ROW LEVEL SECURITY` is actually doing its job).
- [ ] Turn on basic **logging/monitoring** in Cloud Run.
- [ ] Double-check **budget alerts** are active.

---

## Monthly cost at MVP scale (rough, USD)

| Item | Cost |
|---|---|
| Cloud SQL (small, single-zone, always on) | ~$10–25 |
| Cloud Run (FastAPI, min-instances = 0) | ~$0–5 |
| Cloudflare Pages (frontend) | Free |
| Identity Platform (well under free-tier MAU) | ~$0 |
| Cloud Storage — raw data (see below) | pennies–$2 |
| **Total** | **~$15–35/mo** |

### Raw data storage cost (Cloud Storage, Standard class, US)

Storage is **$0.020/GB/month**, first **5 GB free**. So:

- 10 GB ≈ **$0.20/mo**
- 50 GB ≈ **$1/mo**
- 100 GB ≈ **$2/mo**
- 1 TB ≈ **$20/mo**

If the raw data is just sitting there and rarely read, **Nearline** ($0.010/GB/mo) halves that. At prototype volumes the storage cost is effectively a rounding error — Standard is the simplest choice.

---

## FERPA note (carry forward, don't build yet)

Two things make compliance *easier to prove* later, and both are nearly free to honor now:
1. **App connects as a non-superuser, non-owner role + FORCE RLS** — so isolation is enforced at the database, not just in app code.
2. **Every private row has a consistent `tenant_id`** and no query ever joins across tenants on private data — this keeps the option open to peel a tenant into its own database/schema when a real FERPA contract lands.

Compliance certifications (SOC2, BAA-style terms) live on higher-cost tiers and don't matter for a public-data prototype — just know that step exists for when student records become real.

---

## Decisions locked for MVP

- **Auth provider: Identity Platform.** Settled. Swappable later if you ever want prebuilt org/membership UI — not an MVP concern.
- **Access control: RLS in Postgres only, flat within org.** Tenant isolation via `tenant_id` + `FORCE ROW LEVEL SECURITY` is the *sole* access gate. Every authenticated member of an org sees all of that org's data — no roles, no per-user rules in the MVP.
- **Tenant granularity: the district.** Private data is district-level; the org/tenant *is* the district. No school- or student-level structure in the MVP.
- **ReBAC + finer granularity: out of scope for MVP.** Deferred together to a later version (see note below).

## What this simplifies

- RLS policies are the **simplest possible**: scope private rows to the current tenant, full stop. No role checks, no relationship walking, no per-school or per-user policies.
- **No role column, no rosters, no school→district hierarchy tables needed now** — MVP data is flat and district-level, so don't build them yet.
- The only forward-compat discipline that still matters: keep **`tenant_id` consistent on every private row** and never join across tenants. That's already in Phase 1.

**Note — FERPA and ReBAC arrive together.** District-level aggregate data is generally *not* FERPA-covered PII. The moment the data gets granular enough to be FERPA-sensitive (school- or student-level records) is the same moment you'd add ReBAC. So "go granular," "FERPA contract," and "implement ReBAC" are one future milestone, not three — handle them as a set when you get there.
