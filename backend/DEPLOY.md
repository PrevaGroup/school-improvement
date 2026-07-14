# Deploy the FastAPI backend to Cloud Run

Container: [`Dockerfile`](Dockerfile) (build context = `backend/`). DB access uses the
Cloud SQL Python Connector when `INSTANCE_CONNECTION_NAME` is set (no Auth Proxy
sidecar needed on Cloud Run); locally it falls back to the Auth-Proxy URL.

## Prerequisites (one-time)

1. **Secrets in Secret Manager** (project `school-improvement-501916`):
   - `sip-app-password`, `sip-migrator-password` — already exist (runbook Phase 3).
   - `anthropic-api-key` — **create this** for `POST /plans/extract`:
     ```bash
     printf %s "sk-ant-..." | gcloud secrets create anthropic-api-key --data-file=-
     ```
2. **Grant the Cloud Run service account** `roles/secretmanager.secretAccessor` and
   `roles/cloudsql.client`.

## Anthropic key & credits (don't rely on a reminder)

Two separate things fail, with different fixes:

- **Credits run dry** (the balance, not the key). Set **Auto-reload** in the Anthropic
  Console → Plans & Billing, plus a low-balance email alert. This is the forget-proof fix —
  the balance can't hit zero unattended. (Anthropic bills separately from GCP.)
- **Key rotated / revoked / (org-policy) expired.** API keys are long-lived; they don't
  expire on a timer unless your org enforces it. To rotate, add a new secret version — the
  app reads `latest`, so **no code change, no redeploy**:
  ```bash
  printf %s "sk-ant-NEWKEY" | gcloud secrets versions add anthropic-api-key --data-file=-
  ```
  A dead key surfaces cleanly as `Anthropic API 401: … → check the anthropic-api-key secret`
  (extract_sip maps Anthropic HTTP errors to a one-line message; `/plans/extract` → 502).

## Deploy

```bash
gcloud run deploy sip-api \
  --source backend \
  --region us-central1 \
  --add-cloudsql-instances school-improvement-501916:us-central1:school-improvement-sql \
  --set-env-vars GCP_PROJECT=school-improvement-501916 \
  --set-env-vars INSTANCE_CONNECTION_NAME=school-improvement-501916:us-central1:school-improvement-sql \
  --set-env-vars DB_NAME=sip,DB_IP_TYPE=public,DEV_MODE=false \
  --min-instances 0 \
  --max-instances 4 \
  --no-allow-unauthenticated
```

- **`--max-instances 4`** caps serverless scale-out so it can't exhaust Postgres
  connections (runbook Phase 3). The engine also uses `pool_pre_ping`.
- **`--min-instances 0`** for MVP — accept occasional cold starts (free).
- The Anthropic key is read from Secret Manager via ADC at request time; no env var
  needed in prod. (Set `ANTHROPIC_API_KEY` only for a local dev fallback.)
- **`--no-allow-unauthenticated`** is the access gate: only Google identities you grant
  `roles/run.invoker` can reach the service (this is how "who's asking" and your Claude
  spend are controlled — see below). No app-level login is built.

## Chat UI (`GET /` + `POST /chat`)

The chat page is served from the app itself (`app/static/index.html`), so it's **one Cloud
Run service behind one IAM gate** — no separate frontend host, no CORS. It calls
`POST /chat`, which runs Claude (`settings.chat_model`, Haiku by default for cost) with an
inline tool over the public `plan_extraction` + `fact_metric` marts. All reads are public
(SPSAs are public docs), so there's no tenant/auth in the app — access is the IAM gate.

Grant demo users access:
```bash
gcloud run services add-iam-policy-binding sip-api --region us-central1 \
  --member="user:teammate@example.com" --role="roles/run.invoker"
```
They then reach it via an identity-aware proxy token (or `gcloud run services proxy sip-api
--region us-central1` for a local authenticated tunnel).

## Auth (GCIP)

Token verification is implemented in `app/security.py` (`verify_firebase_token` via
`google-auth`). Two things must be in place for `DEV_MODE=false`:

- **Audience** = the GCP project (the token's `aud`). Defaults to `GCP_PROJECT`; no extra
  env var needed unless you override with `GOOGLE_OAUTH_AUDIENCE`.
- **Identity → tenant**: set a `tenant_id` **custom claim** on each user at provisioning
  (recommended), or configure `DOMAIN_TENANT_MAP` (e.g. `{"lbschools.net":"lbusd"}`) to
  map by email domain. The resolved tenant must exist in `dim_tenant`.

For a gated internal test without real sign-in, deploy with `DEV_MODE=true` and call with
an `X-Dev-Tenant: <tenant_id>` header.

## ⚠️ Remaining before a real prod cutover

- **Provisioning**: a way to create GCIP users and attach the `tenant_id` custom claim
  (`firebase-admin` / Identity Platform Admin API) — one-time onboarding, not the request
  path. Until then, use `DOMAIN_TENANT_MAP` or dev mode.
- Create the `anthropic-api-key` secret (above) and confirm the tenant rows exist in
  `dim_tenant`.
