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
