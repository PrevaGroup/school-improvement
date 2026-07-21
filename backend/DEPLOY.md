# Deploy the FastAPI backend to Cloud Run

Container: [`../Dockerfile`](../Dockerfile) — **at the repo root**, multi-stage: a node stage
runs `vite build` on `frontend/`, then the python stage serves the API *and* that bundle from
one origin. The context is the repo root because a stage that compiles `frontend/` cannot see
it from a `backend/` context. DB access uses the
Cloud SQL Python Connector when `INSTANCE_CONNECTION_NAME` is set (no Auth Proxy
sidecar needed on Cloud Run); locally it falls back to the Auth-Proxy URL.

> **This document describes the live, internet-reachable deploy** — the go-live cutover
> ran **2026-07-16**. The service is `--allow-unauthenticated` on `sip.prevagroup.com`
> (and its `run.app` aliases); the boundary is the app's own Identity Platform sign-in +
> the domain allowlist, and Claude spend is capped in-app (`app/usage.py`). The plan that
> got here, with the rationale for each step, is
> [`docs/GO_LIVE_PLAN.md`](../docs/GO_LIVE_PLAN.md) — now a historical record.

## Prerequisites (one-time)

1. **Secrets in Secret Manager** (project `school-improvement-501916`):
   - `sip-app-password`, `sip-migrator-password` — already exist (runbook Phase 3).
   - `anthropic-api-key` — also exists (used by `POST /plans/extract` and `/api/chat`).
     In a fresh project, create it with:
     ```bash
     printf %s "sk-ant-..." | gcloud secrets create anthropic-api-key --data-file=-
     ```
2. **Grant the Cloud Run service account** `roles/secretmanager.secretAccessor` and
   `roles/cloudsql.client`.
3. **Chat trace emission** (`docs/design/eval-trace-system.md` phase 1; with TRACES_BUCKET
   unset the app runs with tracing disabled. **This infra ran 2026-07-16** — bucket, salt
   secret, and the IAM grant all exist; in a fresh project redo all three):
   - Bucket, with the 90-day lifecycle rule set AT CREATION (retention decision §8.3):
     ```bash
     gcloud storage buckets create gs://school-improvement-traces --location=us-central1
     printf '{"rule":[{"action":{"type":"Delete"},"condition":{"age":90}}]}' > /tmp/lc.json
     gcloud storage buckets update gs://school-improvement-traces --lifecycle-file=/tmp/lc.json
     ```
   - Salt for `principal_hash` (identity in traces is hashed, never raw):
     ```bash
     python3 -c "import secrets; print(secrets.token_hex(32))" | tr -d '\n' \
       | gcloud secrets create trace-principal-salt --data-file=-
     ```
   - Grant the service account `roles/storage.objectCreator` on the bucket.
   - `TRACES_BUCKET` + `GIT_SHA` ride in the ONE `--set-env-vars` flag — already shown in
     the Deploy block below (`GIT_SHA` is what lets a trace attribute a delta to a code
     change, so stamp it from the checkout you actually deploy).
   - A missing piece never breaks chat: flushes are fire-and-forget and log a warning instead
     of raising. Grep Cloud Logging for `chat_trace` (the per-turn ops line) to confirm
     traces flow, and for `trace flush failed` to catch a misconfiguration.

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
  --set-env-vars GCP_PROJECT=school-improvement-501916,INSTANCE_CONNECTION_NAME=school-improvement-501916:us-central1:school-improvement-sql,DB_NAME=sip,DB_IP_TYPE=public,DEV_MODE=false,ALLOWED_DOMAIN_PROVIDERS=prevagroup.com=google.com,ADMIN_GROUP=usersupport@prevagroup.com,TRACES_BUCKET=school-improvement-traces,GIT_SHA=$(git rev-parse HEAD) \
  --min-instances 0 \
  --max-instances 4 \
  --allow-unauthenticated
```

### Administrators — Workspace group `ADMIN_GROUP` (one-time GCP setup)

`is_admin` (app/security.py) checks the caller's verified email against membership in the
`ADMIN_GROUP` Google Workspace group **live** via the Cloud Identity API — so the admin roster
is managed in the Workspace admin console (add/remove a member of `usersupport@prevagroup.com`),
no deploy. It **fails closed**: until the two setup steps below are done, `is_admin` returns
False for everyone (logged as a warning), which is safe — nobody is wrongly elevated.

1. **Enable the Cloud Identity API** on the project:
   `gcloud services enable cloudidentity.googleapis.com --project school-improvement-501916`
2. **Let the Cloud Run runtime service account read the group's membership.** Find the SA
   (`gcloud run services describe sip-api --region us-central1 --format='value(spec.template.spec.serviceAccountName)'`;
   empty = the default compute SA `PROJECT_NUMBER-compute@developer.gserviceaccount.com`). Then
   grant it view access to the group — the simplest is to **add that SA email as a member of
   `usersupport@prevagroup.com`** (a member can check the group's transitive membership); a
   Workspace super-admin does this in the Groups console. (Alternative: grant the SA the
   Groups Reader admin role.) A wrong/absent grant just keeps everyone non-admin — verify via
   the `admin group check failed …` warning in the logs.

**Extra admin sources** (UNIONed with the group): `ADMIN_EMAILS` (exact addresses) and
`ADMIN_DOMAINS` (whole domains, e.g. `prevagroup.com` = every verified preva user is admin).
These need no Cloud Identity setup — a match is admin immediately.

**Testing admin with a personal account** — a `@gmail.com` normally can't sign in (the invite
gate is domain-bound), so two env vars are needed together:
- `ALLOWED_EMAILS=you@gmail.com` — lets that EXACT address through the invite gate (still
  requires `email_verified`; skips the domain/provider binding — a deliberate hole, per-email
  only). ⚠️ This bypasses "access must ride a revocable org identity"; it is a TEST hatch —
  remove it before relying on that guarantee.
- `ADMIN_EMAILS=you@gmail.com` — makes that address an admin.
Both go in the single `--set-env-vars` flag. The frontend already routes `gmail.com` to the
Google popup, so the address can sign in; the backend allowlist is the real gate.

> ⚠️ **The `--allow-unauthenticated` flag is not a no-op on redeploys — it MANAGES the IAM
> binding.** The gate opened for real on 2026-07-16 (`allUsers` granted `run.invoker`;
> the app's sign-in + allowlist is the boundary). Redeploying with
> `--no-allow-unauthenticated` — say, by reusing this block from an old shell history —
> **removes that binding and re-closes the gate**, and every tester starts seeing 403s
> until someone re-runs `gcloud run services add-iam-policy-binding sip-api
> --member=allUsers --role=roles/run.invoker`. (This happened once, caught within the
> minute.) Omitting the flag entirely leaves the existing policy alone, which is also fine.

- **`--max-instances 4`** caps serverless scale-out so it can't exhaust Postgres
  connections (runbook Phase 3). The engine also uses `pool_pre_ping`.
- **`--min-instances 0`** is still the deployed value (verified against the live service
  2026-07-16). The go-live plan called for `--min-instances 1` (~$6–15/mo) so an invited
  tester's first click doesn't pay a container start *plus* a Cloud SQL connect — that reads
  as "broken", not "thrifty". **Open item:** bump it, or decide cold starts are acceptable
  and update this line.
- **`--source .` runs from the repo root** (`school-improvement/` — where `.git` is, not the
  parent `SchoolImprovement/`), because the multi-stage Dockerfile builds `frontend/` and
  cannot see it from a `backend/` context.
  - **Size is fine:** the repo is **4.8 MB** (measured 2026-07-15). The 2.8 GB `California/`
    raw data is a **sibling outside the repo** and was never in scope for upload.
  - **`.gcloudignore` footgun:** with **no** `.gcloudignore`, gcloud auto-generates one that
    honors `.gitignore`. **Hand-writing one turns that off** — the root
    [`.gcloudignore`](../.gcloudignore) therefore starts with `#!include:.gitignore` (which
    covers `node_modules`, `dist`, `__pycache__/`, `.venv/`, `.pytest_cache/`) and then adds
    `.git/`. Keep that include line when editing the file.
  - **`.dockerignore` lives at the context root** — Docker only reads it there. The old
    `backend/.dockerignore` was deleted (it would be inert but look authoritative). The root
    [`.dockerignore`](../.dockerignore) excludes `node_modules/` and `frontend/dist/` (built
    inside the image) while **keeping `frontend/` source**, which build stage 1 needs.
- The Anthropic key is read from Secret Manager via ADC at request time; no env var
  needed in prod. (Set `ANTHROPIC_API_KEY` only for a local dev fallback.)
- **`ALLOWED_DOMAIN_PROVIDERS` is required** — every `/api` route demands a verified,
  invited identity, and the map fails closed: forget it and every signed-in user 403s with
  "not on the invite list". `prevagroup.com=google.com` only until Entra lands (a single
  entry, so no comma and no `^@^` needed yet — see the invite-list section below for when
  gatesfoundation.org joins). The `=` **inside** the value is fine: gcloud splits each
  entry on the *first* `=` only. This var superseded `ALLOWED_EMAIL_DOMAINS` (#41); an
  earlier revision of this block still showed the old name, and copying it into a redeploy
  on 2026-07-16 would have silently downgraded the live auth config — this block is
  reconciled against `gcloud run services describe`, keep it that way.
- **`TRACES_BUCKET` + `GIT_SHA` turn on chat trace emission** (prerequisite 3 above must
  have run once). Both are optional in the strict sense — dropping them just disables
  tracing, chat is unaffected — but a deploy that forgets them silently stops feeding the
  eval loop, so treat them as part of the standard flag.
- **Migration 0005 (`usage_chat_daily`) is applied** — it ran before the go-live deploy.
  Still worth knowing: /api/chat refuses (503, fails closed) if the spend counter table is
  ever missing, so a fresh environment must reach `alembic upgrade head` (from Cloud Shell
  per `backend/README.md`) before chat works.
- **Claude spend caps** (in-app, §3.4 — the IAM gate's replacement for its second job):
  `CHAT_DAILY_USER_USD` (default $2/day per signed-in user, ~10–40 heavy messages) and
  `CHAT_DAILY_GLOBAL_USD` (default $20/day everyone combined — the ceiling that holds no
  matter how many allowlisted users show up). Over either → 429 until midnight UTC. Raw
  token counts land per (user, day, model); dollars are derived from the price table in
  `app/usage.py` — update it there when Anthropic reprices.
- **The access gate is the app's own sign-in** (verified Identity Platform token +
  `ALLOWED_EMAIL_DOMAINS`), not Cloud Run IAM — since the 2026-07-16 go-live the service
  is `--allow-unauthenticated` and the spend caps above bound the Claude exposure. The
  historical IAM-gated posture (grant individual `roles/run.invoker`, reach via
  `gcloud run services proxy`) remains useful for pre-release smoke tests of a closed
  revision.

> **History:** until 2026-07-16, `--no-allow-unauthenticated` did two jobs — access gate
> *and* the only Anthropic spend cap. Both replacements shipped before the flag flipped:
> sign-in + allowlist enforcement in [`app/security.py`](app/security.py), and the in-app
> spend caps in [`app/usage.py`](app/usage.py) (whose docstring keeps the full rationale).

## Chat UI (`GET /` + `POST /chat`)

The UI is the React + Vite SPA in [`frontend/`](../frontend), built into the image and served
by FastAPI itself — **one Cloud Run service, one origin**, so no separate frontend host and no
CORS. It calls `POST /api/chat`, which runs Claude (`settings.chat_model`, Haiku by default for
cost) with an inline tool over the public `plan_extraction` + `fact_metric` marts. All reads
are public (SPSAs are public docs), so there is **no tenant** in the app — but every `/api`
route is Identity Platform-authenticated: the sign-in + allowlist is what replaced the IAM
gate at go-live.

For a pre-release smoke test of a **closed** revision (the historical IAM-gated posture),
grant an individual invoker:
```bash
gcloud run services add-iam-policy-binding sip-api --region us-central1 \
  --member="user:teammate@example.com" --role="roles/run.invoker"
```
and reach it via an identity-aware proxy token (or `gcloud run services proxy sip-api
--region us-central1` for a local authenticated tunnel). The live service doesn't need any of
this — it's `--allow-unauthenticated`; users just sign in.

## Who may sign in — `ALLOWED_DOMAIN_PROVIDERS` (the invite list, with teeth)

**Authentication is not invitation.** With Identity Platform's Google provider enabled, *any* Gmail account
can obtain a valid token for this project. Verifying the token therefore gates **nothing** on
its own — it proves the caller exists, not that you invited them. This map is
what turns "signed in" into "invited", and it is what stands between the open internet and the
Anthropic balance behind `/api/chat`.

```bash
ALLOWED_DOMAIN_PROVIDERS=prevagroup.com=google.com,gatesfoundation.org=microsoft.com
```

One table, three jobs:
- **Invitation** — the keys are the invited domains (everything below about exact matching
  and failing closed applies to them).
- **Routing** — the SPA's email-first screen mirrors this map (`frontend/src/auth-routing.ts`)
  to send each user to their org's own popup. Keep the two in step when adding an org.
- **Enforcement** — `security.py` 403s any token whose server-set `sign_in_provider` doesn't
  match the domain's entry. This is the revocability constraint made structural: preva
  identities are Workspace-managed, gates identities are Entra; a *personal* Google account
  on a work address survives offboarding and is therefore not an acceptable identity, even
  with the right email.

The older `ALLOWED_EMAIL_DOMAINS=prevagroup.com,...` still works and maps every listed
domain to `google.com` — correct for the preva-only era, so a redeploy from old shell
history stays safe. Prefer the map for anything new.

### Adding an Entra org (Phase B checklist, in order)

1. Azure: multi-tenant **app registration** (free account) — redirect URI
   `https://sip.prevagroup.com/__/auth/handler`, NO permissions beyond OIDC defaults
   (`openid email profile` — the shortest possible consent review).
2. Identity Platform → Providers → **Microsoft**: paste the registration's client ID +
   secret (same field-swap trap as Google, see above).
3. Add `<org-domain>=microsoft.com` to `ALLOWED_DOMAIN_PROVIDERS` and un-comment the same
   entry in `frontend/src/auth-routing.ts`; deploy.
4. First sign-in from the org either works (their tenant allows user consent — rare) or
   throws `AADSTS90094` admin-consent-required, which usually carries a request-approval
   flow into their IT queue. That request IS the ask; there is no shortcut around a
   consent-locked tenant.

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
>   --set-env-vars ^@^GCP_PROJECT=school-improvement-501916@ALLOWED_DOMAIN_PROVIDERS=prevagroup.com=google.com,gatesfoundation.org=microsoft.com@DEV_MODE=false
> ```
>
> Without it you get `ALLOWED_DOMAIN_PROVIDERS=prevagroup.com=google.com` plus a bogus
> `gatesfoundation.org` env var holding `microsoft.com` — and a silently *shorter* invite
> list. (Same class of footgun as the "all env vars in ONE flag" note above.) The `=` signs
> inside the value are never the problem — gcloud splits entries on the first `=` only; the
> comma is.

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

For a **local** test without real sign-in, run with `DEV_MODE=true` and call with an
`X-Dev-Tenant: <tenant_id>` header. Local only — on Cloud Run the app refuses to boot with
`DEV_MODE=true` (next note).

> ⚠️ **`DEV_MODE` cannot reach production — structurally, not by convention.** The
> `X-Dev-Tenant` header is unverified by construction — on a publicly reachable service it
> would be tenant impersonation via a request header. So the app **refuses to boot** with
> `DEV_MODE=true` when a production signal (`K_SERVICE`, `INSTANCE_CONNECTION_NAME`) is
> present ([`app/security.py`](app/security.py) `assert_dev_mode_not_in_production`, tested
> in `tests/test_security.py`). The env-signal gate exists because a `DEV_MODE=false`
> deploy flag alone is not sufficient — it's one hurried `--set-env-vars` edit away from
> true. Fail the deploy, not the security model.

## Custom domain — `sip.prevagroup.com` (mapped 2026-07-16)

Cloud Run **domain mapping**. No load balancer, no proxy, no Workers.

> **Reality correction (2026-07-16):** earlier drafts of this section were written around
> a third-party proxying DNS provider. **prevagroup.com's DNS was never on one** — its
> nameservers are `ns-cloud-b*.googledomains.com` (Google-hosted DNS,
> managed through the Squarespace panel after the Google Domains sale). The plan assumed
> otherwise and the docs repeated it without an NS lookup. There is no proxy toggle on
> Google-hosted DNS, so the whole proxied-CNAME failure class (proxy hides the CNAME →
> Google's managed cert never provisions) is structurally absent here; the old warnings
> apply only if DNS ever actually moves to a proxying provider.

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

## Go-live status (cutover ran 2026-07-16)

Everything the plan gated the cutover on shipped before the gate opened
([`docs/GO_LIVE_PLAN.md`](../docs/GO_LIVE_PLAN.md) has the sequenced history):

- ✅ **Auth split from tenancy** in `app/security.py` — `get_current_principal` (verify
  only) gates every `/api` route; `get_current_tenant` (verify + map, 403s any identity
  without a mapped district) stays reserved for future private routes.
- ✅ **`DEV_MODE` locked out of prod** — structural boot refusal (above).
- ✅ **Claude spend capped in-app** — per-user and global daily caps in `app/usage.py`,
  keyed on the verified Identity Platform subject.
- ✅ **Custom domain mapped and in Identity Platform authorized domains**
  (`sip.prevagroup.com`).
- ✅ **`anthropic-api-key` secret** created; read via ADC at request time.

Still open:

- **`--min-instances` is still 0** — the plan called for 1 at go-live so testers don't pay
  cold starts (see the deploy-flags notes above). Bump it or decide to accept cold starts.
- **Tenant provisioning** — a way to create Identity Platform users with the `tenant_id`
  custom claim (`firebase-admin` / Identity Platform Admin API) and matching `dim_tenant`
  rows. Not needed until private district data lands: public-data testers need no claim.
