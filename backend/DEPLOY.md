# Deploy the FastAPI backend to Cloud Run

Container: [`../Dockerfile`](../Dockerfile) — **at the repo root**, multi-stage: a node stage
runs `vite build` on `frontend/`, then the python stage serves the API *and* that bundle from
one origin. The context is the repo root because a stage that compiles `frontend/` cannot see
it from a `backend/` context. DB access uses the
Cloud SQL Python Connector when `INSTANCE_CONNECTION_NAME` is set (no Auth Proxy
sidecar needed on Cloud Run); locally it falls back to the Auth-Proxy URL.

> **This document describes the current IAM-gated demo deploy.** The cutover to a
> Identity Platform-authenticated, internet-reachable service on a custom domain is planned in
> [`docs/GO_LIVE_PLAN.md`](../docs/GO_LIVE_PLAN.md). Two things here change at that
> cutover, and both are called out inline below:
> - the **build context moves to the repo root** (`--source .`), because a multi-stage
>   build that compiles `frontend/` cannot see it from a `backend/` context;
> - **`--no-allow-unauthenticated` goes away**, which removes both the access gate *and*
>   the Claude spend cap. Do not remove it before its replacements exist.

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
# NOTE: all env vars go in ONE --set-env-vars flag — repeating the flag overwrites
# (last wins), which would silently drop GCP_PROJECT + INSTANCE_CONNECTION_NAME.
gcloud run deploy sip-api \
  --source . \
  --region us-central1 \
  --add-cloudsql-instances school-improvement-501916:us-central1:school-improvement-sql \
  --set-env-vars GCP_PROJECT=school-improvement-501916,INSTANCE_CONNECTION_NAME=school-improvement-501916:us-central1:school-improvement-sql,DB_NAME=sip,DB_IP_TYPE=public,DEV_MODE=false,ALLOWED_EMAIL_DOMAINS=prevagroup.com \
  --min-instances 0 \
  --max-instances 4 \
  --no-allow-unauthenticated
```

- **`--max-instances 4`** caps serverless scale-out so it can't exhaust Postgres
  connections (runbook Phase 3). The engine also uses `pool_pre_ping`.
- **`--min-instances 0`** for MVP — accept occasional cold starts (free). **At go-live this
  becomes `--min-instances 1`** (~$6–15/mo): an invited tester's first click shouldn't pay a
  container start *plus* a Cloud SQL connect. That reads as "broken", not "thrifty".
- **At go-live the source flag changes** to `--source .`, run from the repo root
  (`school-improvement/` — where `.git` is, not the parent `SchoolImprovement/`), because the
  multi-stage Dockerfile builds `frontend/` and cannot see it from a `backend/` context.
  - **Size is already fine:** the repo is **4.8 MB** (measured 2026-07-15). The 2.8 GB
    `California/` raw data is a **sibling outside the repo** and was never in scope for upload.
  - **`.gcloudignore` footgun:** with **no** `.gcloudignore`, gcloud auto-generates one that
    honors `.gitignore`. **Hand-writing one turns that off** — so a file that forgets
    `node_modules/` will upload it the first time anyone runs `npm install`. Start it with
    `#!include:.gitignore` (already covers `node_modules`, `dist`, `__pycache__/`, `.venv/`,
    `.pytest_cache/`), then add `.git/`.
  - **`.dockerignore` moves too:** Docker only reads it **at the context root**, so
    [`backend/.dockerignore`](.dockerignore) becomes **inert** — delete it rather than leave it
    looking authoritative. The root one must exclude `node_modules/` and `frontend/dist/`
    (built inside the image) while **keeping `frontend/` source**, which build stage 1 needs.
- The Anthropic key is read from Secret Manager via ADC at request time; no env var
  needed in prod. (Set `ANTHROPIC_API_KEY` only for a local dev fallback.)
- **`ALLOWED_EMAIL_DOMAINS` is required from this deploy on** — every `/api` route now
  demands a verified, invited identity, and the allowlist fails closed: forget it and
  every signed-in user 403s with "not on the invite list". `prevagroup.com` only until
  Entra lands (a single value, so no comma and no `^@^` needed yet — see the allowlist
  section below for when gatesfoundation.org joins).
- **Migration 0005 must run before the next deploy** (`alembic upgrade head`, from Cloud
  Shell per `backend/README.md`) — /api/chat now refuses (503, fails closed) if the
  `usage_chat_daily` spend counter is missing.
- **Claude spend caps** (in-app, §3.4 — the IAM gate's replacement for its second job):
  `CHAT_DAILY_USER_USD` (default $2/day per signed-in user, ~10–40 heavy messages) and
  `CHAT_DAILY_GLOBAL_USD` (default $20/day everyone combined — the ceiling that holds no
  matter how many allowlisted users show up). Over either → 429 until midnight UTC. Raw
  token counts land per (user, day, model); dollars are derived from the price table in
  `app/usage.py` — update it there when Anthropic reprices.
- **`--no-allow-unauthenticated`** is the access gate: only Google identities you grant
  `roles/run.invoker` can reach the service (this is how "who's asking" and your Claude
  spend are controlled — see below). No app-level login is built.

> ⚠️ **`--no-allow-unauthenticated` is doing two jobs, and it's easy to only notice one.**
> It gates access *and* it is the only thing capping Anthropic spend — there is no
> per-user limit in the app, and `/chat` is unauthenticated at the application layer
> ([`app/chat.py`](app/chat.py) reads `get_db_public`). Flipping this to
> `--allow-unauthenticated` therefore exposes `POST /chat` and `POST /plans/extract` (an
> Opus call per PDF) to anyone who finds the `run.app` URL. **The replacements — Identity Platform
> enforcement, the `DEV_MODE` lockout, and an in-app per-user chat cap — must land first.**
> See [`docs/GO_LIVE_PLAN.md`](../docs/GO_LIVE_PLAN.md) §3.4 and §3.6.

## Chat UI (`GET /` + `POST /chat`)

The UI is the React + Vite SPA in [`frontend/`](../frontend), built into the image and served
by FastAPI itself — **one Cloud Run service, one origin**, so no separate frontend host and no
CORS. It calls `POST /api/chat`, which runs Claude (`settings.chat_model`, Haiku by default for
cost) with an inline tool over the public `plan_extraction` + `fact_metric` marts. All reads are
public (SPSAs are public docs), so there's no tenant/auth in the app yet — access is still the
IAM gate until Identity Platform sign-in lands.

> **At go-live this page is replaced**, but the *single-origin* property it demonstrates is
> kept deliberately: the React + Vite SPA is built into the same image and served by the same
> FastAPI app, so there is still one host and still no CORS. Routes move under `/api/*`, and
> "no tenant/auth in the app" becomes "**no tenant**, but Identity Platform-authenticated" — the reads stay
> public; the sign-in is what replaces the IAM gate.

Grant demo users access:
```bash
gcloud run services add-iam-policy-binding sip-api --region us-central1 \
  --member="user:teammate@example.com" --role="roles/run.invoker"
```
They then reach it via an identity-aware proxy token (or `gcloud run services proxy sip-api
--region us-central1` for a local authenticated tunnel).

## Who may sign in — `ALLOWED_EMAIL_DOMAINS` (the invite list)

**Authentication is not invitation.** With Identity Platform's Google provider enabled, *any* Gmail account
can obtain a valid token for this project. Verifying the token therefore gates **nothing** on
its own — it proves the caller exists, not that you invited them. `ALLOWED_EMAIL_DOMAINS` is
what turns "signed in" into "invited", and it is what stands between the open internet and the
Anthropic balance behind `/api/chat`.

```bash
ALLOWED_EMAIL_DOMAINS=prevagroup.com,gatesfoundation.org
```

- **Comma-separated, exact domains.** `mail.prevagroup.com` does **not** match `prevagroup.com`
  — suffix matching is how allowlists get bypassed (`notprevagroup.com`,
  `prevagroup.com.evil.tld`), and the list is short enough to spell out.
- **It fails closed.** Unset = **nobody gets in**. A deploy that forgets it locks people out
  (loud, fixable) rather than opening the door (silent, expensive). If everyone is suddenly
  403ing with *"not on the invite list"*, this is why.
- **`email_verified` is enforced alongside it** (`app/security.py`). Not optional: a token
  proves Identity Platform issued it, **not** that the address inside belongs to the caller. Identity Platform's
  email/password provider lets anyone register any address unverified — so a domain check
  without the verified check is an honour system.

> **⚠️ The comma is why this is not JSON.** `--set-env-vars` splits on commas itself, so a JSON
> list would be shredded into garbage keys. Use gcloud's alternate delimiter to pass a value
> that contains commas — the `^@^` prefix makes `@` the separator instead:
>
> ```bash
> gcloud run deploy sip-api --source . --region us-central1 \
>   --set-env-vars ^@^GCP_PROJECT=school-improvement-501916@ALLOWED_EMAIL_DOMAINS=prevagroup.com,gatesfoundation.org@DEV_MODE=false
> ```
>
> Without it you get `ALLOWED_EMAIL_DOMAINS=prevagroup.com` plus a bogus
> `gatesfoundation.org=` key — and a silently *shorter* invite list. (Same class of footgun as
> the "all env vars in ONE flag" note above.)

## Auth (Identity Platform)

### Provisioning the Google provider — the traps, in the order they bite

Hard-won on 2026-07-16 (each of these produced a different opaque error during the first
real sign-in). The Entra/gatesfoundation.org setup will re-walk this list.

1. **The provider's two fields are easy to swap, and the console won't stop you.**
   Identity Platform → Providers → Google: **Web Client ID** takes the
   `…apps.googleusercontent.com` value; **Web Client Secret** takes the `GOCSPX-…` value.
   The client's display *name* belongs in neither. Symptom of a swap: Google's consent
   screen fails with **`Error 401: invalid_client — The OAuth client was not found`**.
2. **The OAuth client must be type "Web application" and carry the Firebase handler as an
   authorized redirect URI**: `https://school-improvement-501916.firebaseapp.com/__/auth/handler`.
   (APIs & Services → Credentials → the client → Authorized redirect URIs; changes take a
   few minutes to propagate.) Symptom when missing: **`redirect_uri_mismatch`** — and a
   "Desktop" type client has no redirect-URI section at all; recreate it as Web application.
3. **Account linking must be "Link accounts that use the same email"**
   (`signIn.allowDuplicateEmails=false`). Under "create multiple accounts per identity
   provider", email stops being an identity property and **ID tokens omit the email claim
   entirely** — so the allowlist (correctly, failing closed) rejects every user as
   *"signed in as (no email)"*. Worse, user records created under that mode stay
   email-less forever, even after the setting is fixed: **delete the affected records**
   (Identity Platform → Users) and have them sign in fresh.
4. **`localhost` and `127.0.0.1` are different authorized domains.** The default list
   covers `localhost`; a proxy smoke test opened at `http://127.0.0.1:8080` fails with
   `auth/unauthorized-domain`. Use `http://localhost:<port>`, or add `127.0.0.1`.
5. **Cloud Run has two URL formats, and authorized domains are exact-match.** The same
   service answers on `<svc>-<hash>-<region-code>.a.run.app` *and*
   `<svc>-<project#>.<region>.run.app`; the console added the old format, the new console
   and gcloud advertise the new one. Symptom: sign-in works on one URL and throws
   `auth/unauthorized-domain` on the other. List every hostname users actually visit —
   including the custom domain when it lands.
6. **The account-chooser shows the raw authDomain until Google verifies the brand** —
   setting the Branding page's App name alone does NOT change "to continue to
   school-improvement-501916.firebaseapp.com". Our fix: `authDomain` is
   `sip.prevagroup.com` and the backend reverse-proxies Firebase's reserved `/__/*`
   namespace to `<project>.firebaseapp.com` (`app/auth_proxy.py`), so the chooser names
   our domain. Requires `https://sip.prevagroup.com/__/auth/handler` as an **additional
   authorized redirect URI** on the OAuth client (trap #2's page). Bonus: the auth handler
   is first-party now, which retires the Safari/ITP popup flakiness.

### Token verification (runtime)

Token verification is implemented in `app/security.py` (`verify_firebase_token` via
`google-auth`). Two things must be in place for `DEV_MODE=false`:

- **Audience** = the GCP project (the token's `aud`). Defaults to `GCP_PROJECT`; no extra
  env var needed unless you override with `GOOGLE_OAUTH_AUDIENCE`.
- **Identity → tenant**: set a `tenant_id` **custom claim** on each user at provisioning
  (recommended), or configure `DOMAIN_TENANT_MAP` (e.g. `{"lbschools.net":"lbusd"}`) to
  map by email domain. The resolved tenant must exist in `dim_tenant`.

For a gated internal test without real sign-in, deploy with `DEV_MODE=true` and call with
an `X-Dev-Tenant: <tenant_id>` header.

> ⚠️ **`DEV_MODE=true` is safe *only* while `--no-allow-unauthenticated` holds.** The
> `X-Dev-Tenant` header is unverified by construction — on a publicly reachable service it
> is tenant impersonation via a request header, i.e. any caller can read any district. At
> the go-live cutover the app must **structurally refuse** the dev path when a production
> signal (`K_SERVICE`, `INSTANCE_CONNECTION_NAME`) is present. A `DEV_MODE=false` deploy
> flag is not sufficient — it's one hurried `--set-env-vars` edit away from true.

## Custom domain — `sip.prevagroup.com` (mapped 2026-07-16)

Cloud Run **domain mapping**. No load balancer, no proxy, no Workers.

> **Reality correction (2026-07-16):** earlier drafts of this section were written around
> Cloudflare DNS (grey-cloud/orange-cloud doctrine). **prevagroup.com's DNS was never on
> Cloudflare** — its nameservers are `ns-cloud-b*.googledomains.com` (Google-hosted DNS,
> managed through the Squarespace panel after the Google Domains sale). The plan said
> "Cloudflare" and the docs repeated it without an NS lookup. There is no proxy toggle on
> Google-hosted DNS, so the whole orange-cloud failure class is structurally absent here;
> the old warnings apply only if DNS ever actually moves to Cloudflare.

```bash
# NOTE: managed Cloud Run needs the *beta* surface. The GA `gcloud run domain-mappings`
# command is Cloud Run for Anthos and will not do this.
gcloud beta run domain-mappings create \
  --service sip-api --region us-central1 --domain sip.prevagroup.com
```

One-time, per-project, and in this order — each step blocks the next (all executed
2026-07-16):

1. **Verify domain ownership** (`gcloud domains verify prevagroup.com`). Auto-verified
   instantly: the Workspace-era `google-site-verification` TXT record already in DNS is
   accepted as proof. Do not delete that TXT record.
2. Create the mapping; it prints the DNS record to add.
3. **In Squarespace → Domains → prevagroup.com → DNS settings** add:
   CNAME, host `sip`, data `ghs.googlehosted.com.` The CNAME delivers traffic to Google's
   shared front end; the *mapping* is the routing-table entry that tells that front end
   which service owns the hostname. Neither works alone.
4. **Wait** — cert issuance starts once the CNAME is publicly visible. Observed: minutes,
   plus a short edge-propagation lag after `CertificateProvisioned: True` during which
   browsers still see TLS handshake failures (`PR_END_OF_FILE_ERROR`). Normal.
5. **Add the hostname to Identity Platform authorized domains** (see the provisioning
   traps above) — or sign-in fails there with `auth/unauthorized-domain`.

Prefer a **subdomain** (`sip.example.com`). An apex domain needs A/AAAA records instead.

`us-central1` supports domain mappings — verified 2026-07-15 against the regional
`domains.cloudrun.com/v1` endpoint. If a future region doesn't, **flag it** rather than
substituting Firebase Hosting rewrites silently.

### Accepted limitation: `*.run.app` stays reachable — do not "fix" this

Every Cloud Run service answers on its run.app URLs — **both formats**
(`sip-api-4sjiiniraa-uc.a.run.app` and `sip-api-1013838667941.us-central1.run.app` are
aliases of the same service) — alongside any mapped domain. Anyone who finds those URLs
skips the custom domain entirely. **That is accepted and intended: Identity Platform token
verification in FastAPI is the security boundary; the domain is convenience.** It doesn't
care which hostname a request arrived on. Corollary: every hostname users actually visit
must be in Identity Platform's authorized-domains list — exact-match, per name.

So, deliberately: **no load balancer, no ingress restrictions, no hostname-checking
middleware anywhere in the app.** If we ever harden (custom domain via a global LB with
internal ingress), that is a **deliberate infra change — never a scaffold feature.**

## ⚠️ Remaining before a real prod cutover

See [`docs/GO_LIVE_PLAN.md`](../docs/GO_LIVE_PLAN.md) for the sequenced version. In short:

- **Split auth from tenancy** in `app/security.py` — `get_current_principal` (verify only)
  for public routes, `get_current_tenant` (verify + map) for private ones. Today's
  `get_current_tenant` **403s any identity without a mapped district**, so gating the
  public marts on it would reject every outside tester.
- **Lock `DEV_MODE` out of prod** (above). Prerequisite for opening the gate.
- **Cap Claude spend in-app** — per-principal daily limit on `/chat`, keyed on the verified
  Identity Platform subject. Prerequisite for opening the gate.
- **Provisioning**: a way to create Identity Platform users and attach the `tenant_id` custom claim
  (`firebase-admin` / Identity Platform Admin API) — one-time onboarding, not the request
  path. Note public-data testers need **no** claim once auth and tenancy are split.
- Add the custom domain to Identity Platform **authorized domains**, or sign-in fails there with a
  confusing error.
- Create the `anthropic-api-key` secret (above) and confirm the tenant rows exist in
  `dim_tenant`.
