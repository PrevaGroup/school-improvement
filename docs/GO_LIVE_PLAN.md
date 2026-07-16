# Go-live plan — making the prototype reachable on the internet

**Goal:** move from an IAM-gated demo that only Tim can open to a signed-in, publicly
reachable workspace that invited people can play with. "Prototype plus": real sign-in, real
domain, still one service, still public data.

This document is the **sequenced plan** for that cutover. The end-state architecture it
produces is described in [`ARCHITECTURE.md`](../ARCHITECTURE.md); the mechanical runbook is
[`backend/DEPLOY.md`](../backend/DEPLOY.md). Delete this file once the cutover is done.

> **⚠️ Read [§2.5](#25-coordinating-with-the-modular-backend-overhaul) first.** The modular
> backend overhaul ([`MODULES.md`](MODULES.md)) is landing **in parallel** with this plan —
> both were held until after the demo. §2.5 is the collision map. The short version: a small
> `security.py` patch lands **before** the carve-out starts, `chat.py` belongs to **this** plan
> (the reorg excludes it), and everything else is disjoint.

---

## 1. What changes, and what doesn't

| | Today (demo) | After this plan |
|---|---|---|
| Access gate | Cloud Run IAM (`run.invoker`) | **Identity Platform sign-in**, verified per `/api` request |
| Reachable at | `*.run.app`, IAM-gated | your domain (Cloud Run domain mapping) + `*.run.app` |
| Frontend | ~~361-line no-build React from esm.sh~~ | ✅ **React + Vite + TypeScript** in `frontend/`, bundled into the image |
| Origins | one (app serves its own UI) | **still one** — FastAPI serves the built SPA |
| API paths | `/marts/*`, `/chat`, `/schools` | **`/api/*`** |
| Cloudflare | none | **DNS only** (grey cloud, proxy off). No Pages, Access, Workers, Tunnel, or `wrangler.toml`. **Zero repo artifacts** |
| Min instances | 0 | **1** (no cold starts for invited testers) |
| Data served | 100% public marts | **unchanged — still 100% public** |

**Explicitly dropped from the old plan:** Cloudflare Pages (the SPA ships inside the
container instead), Cloudflare Access, Workers, and Tunnel. Choosing Identity Platform for identity and
FastAPI for serving removed both jobs Cloudflare was there to do. Its remaining role is DNS.

> **Why the tunnel was ever in the plan — worth recording, so it doesn't come back.** It was
> load-bearing under an *earlier* shape: a vanilla UI on a box you didn't want exposed, gated
> by Cloudflare Access. Under that plan a tunnel made sense. Moving auth to **Identity Platform** and
> serving to **Cloud Run** evaporated both premises — Cloud Run is already a public HTTPS
> origin, so there is nothing to dial out of, and standing up a VM to host `cloudflared` would
> be architecture in service of a sentence that outlived its design.

**Explicitly still deferred:** the private-tenant `/plans` serving path, per-user roles, and
ReBAC/FERPA. Nothing in this plan makes those harder — the RLS seam stays intact and unused.

---

## 2. The one idea to hold onto

The old plan collapsed two different questions into one word ("auth"). Splitting them is what
makes this cutover small:

| Question | Mechanism | Needed for go-live? |
|---|---|---|
| **Who are you?** (authentication) | Identity Platform verifies an ID token | **Yes.** This is the entire reason the service can be exposed. |
| **What may you see?** (tenancy) | `tenant_id` claim → `SET LOCAL app.tenant` → RLS | **No.** Every served row is public today. |

Everything the demo serves — `/marts/*`, `/chat`, `/schools` — reads `get_db_public`. So
go-live needs **authentication only**. Tenancy stays built, tested, and dormant until the
first private district data lands.

This distinction has a direct code consequence, which is task 3.2 below: today
`get_current_tenant` **403s any identity it can't map to a district**
([`security.py`](../backend/app/security.py)). Gate the public marts on it and every outside
tester without a district is rejected from public data. The verify step and the map step must
become two dependencies.

---

## 2.5 Coordinating with the modular backend overhaul

**The reorg ([`MODULES.md`](MODULES.md)) is running in parallel with this plan.** Both were held
until after the demo. This section is the collision map. **It is written against merged `main`**
— an earlier draft guessed at the reorg's shape and guessed wrong; see the correction below.

**Rule: this plan names *seams*, not file paths.** Paths here (`app/marts.py`, `app/chat.py`)
are where things live *today*; the reorg moves most of them. Where a task names a file, what it
asserts is a contract that survives the move.

### Status: the reorg is ahead of this plan, not behind it

| PR | What it means for go-live |
|---|---|
| **#4** CI + `testpaths` | CI runs on every PR. `testpaths` now includes `tests/`, and `backend/conftest.py` supplies a throwaway DB password so `app/*` imports without credentials. |
| **#5** route contract | `tests/test_route_contract.py` freezes **13 URLs**. **§3.1c's `/api` prefix must update `EXPECTED` in the same commit** — that's the file's own stated protocol for a deliberate contract change. |
| **#6** the seam | Settled as **producer/consumer**, enforced in CI by `tests/test_module_boundaries.py`. |
| **#7** schema inventory | Guards the `core/` carve-out against a silent `DROP TABLE`. |
| **#8** auth split + DEV_MODE | §3.0, §3.2, §3.3 — **done and merged.** |
| **#9** module tables out of `core` | The carve-out has **started**: module-owned tables moved to `likeschools/models.py` + `etl/ca/sip/models.py`. Nothing in go-live imports models, so no overlap — but "land before the reorg" is now **expired** as a strategy. |

### ✅ The `chat.py` crossover — dissolved by #6, not solved

**An earlier version of this plan was wrong, and the record is worth keeping.** It claimed
`chat.py` was "the highest-breakage file, in neither effort's scope," because it imports five
serving functions from `app/marts.py` which would split across `likeschools` / `plan_marts` /
`public_metrics`. It also flagged the underlying seam as unresolvable-for-now: chat owns no
tables and reads none, so the "modules integrate through TABLES" rule had no answer for it.

**#6 dissolved the problem instead of solving it.** The split is by **producer/consumer**, not
by feature: producers (`public_metrics`, `sip`, `likeschools`) own tables; **`serving` owns
none and reads them with SQL**. `chat` and `marts` both land in `serving/`, so those five
imports become *intra*-module and legal — which is why `KNOWN_VIOLATIONS` in the boundary test
doesn't list them. `likeschools` gives up its serving surface to keep the one rule intact.

That is a better answer than this plan proposed. **Nothing in go-live owns `chat.py`;** it is
`serving/`, and the reorg owns it.

**What survived the correction:** `tests/test_chat_tools.py` (#8). It was deliberately written
agnostic to where the code lands — it pins the *call contract*, not the module map — so it
still guards the `app/marts.py` + `app/chat.py` → `serving/` move. Good luck, partly: the
reasoning ("chat has more dependencies on marts than any other consumer, and zero tests") held
even though the predicted breakage didn't.

### What's left to coordinate

| Go-live task | Reorg overlap | Verdict |
|---|---|---|
| 3.1a `frontend/` scaffold | None — `frontend/` is in the target layout, absent from every branch | **Safe** |
| 3.1b Dockerfile → repo root | None — root-level | **Safe** |
| 3.1c `/api/*` prefix | `app/main.py` + must update #5's `EXPECTED` | **⚠️ See the open question below** |
| 3.4 / 3.7 chat work | **`chat.py` → `serving/`** | **Coordinate — `serving/` owns the file** |
| 3.5 Identity Platform provisioning | None — SPA + GCP console | **Safe** |
| 3.6 domain + open the gate | None — deploy flags only | **Safe** (gated on 3.4) |

**`app/main.py` is the composition root** and, per `CLAUDE.md`, *"the one exempt file — keep it
thin."* That settles §3.1c's mechanism: the `/api` prefix and the auth dependency both belong
at the mount, in that file, and nowhere else.

> ### 🚨 OPEN — `/api` vs. the in-flight frontend. Resolve before either side moves.
>
> `tests/test_route_contract.py` pins 13 URLs with **no `/api` prefix**, and its docstring says
> *"the frontend is being rewritten in parallel against these exact URLs."* There is **no
> `frontend/` on any remote branch**, so that work is unpushed and invisible from here.
>
> **§3.1c and that frontend cannot both be right.** Either the frontend adopts `/api` and #5's
> `EXPECTED` is updated in the same commit, or `/api` is dropped and the auth gate needs a
> different mount point. Every day this stays open is a day someone may be building against
> URLs that are about to change. **This is a human decision, not a technical one — it needs
> whoever owns the frontend, not a commit.**

---

## 3. The work, in dependency order

Each task is sized to be independently reviewable. **Task 3.6 (open the gate) must be last** —
that ordering is the plan's main safety property.

### 3.0 — Characterization tests on chat's tool calls — ✅ **DONE (2026-07-15)**

**Shipped in #8.** [`MODULES.md`](MODULES.md) gated code relocation on *"a test safety net"*,
and `chat.py` had **zero tests** while importing **five** `marts` functions — more than any
other consumer. (The original rationale — that those imports would *break* when `marts` split
across modules — turned out wrong: #6 puts `chat` and `marts` both in `serving/`, so they stay
legal. The tests were written agnostic to that, so they still guard the move. See §2.5.)

**Landed:** [`backend/tests/test_chat_tools.py`](../backend/tests/test_chat_tools.py) — 28
tests, **all passing against current behaviour**. No DB: `_resolve_school` and the five
`fetch_*` names are monkeypatched *as `chat` imported them*, so `db` is an inert sentinel.
They pin the two things a relocation would break silently:

1. **The seam** — which mart function each tool calls and with exactly which args. The defaults
   live in *chat*, not marts (`k=10` where marts' own default is 50;
   `metric_id="chronic_absenteeism_rate"`), so they'd vanish without a sound.
2. **The honesty layer** — `plan_status` / `coverage` / `value_status` / `meaning`. This is the
   guardrail against the model claiming a real school "has no attendance plan" when the truth
   is "we haven't loaded its SPSA yet". Nothing else tests it.

> The subtle one worth knowing: **`coverage` is computed *before* the name filter**, so the
> model can distinguish "the plan layer is thin at this level" from "you filtered to one
> school". Computed after, it would always report 1-of-1. That's pinned.

#### Findings from writing them

- **🔴 A dark test directory — found independently, and #4 fixed it better.** `testpaths` read
  `etl app`, so `tests/` was never collected and `tests/test_marts.py` had **never run** in a
  default invocation: a green suite that silently skipped it. #4 landed the same fix
  (`etl app tests`) plus CI, and its `backend/conftest.py` handles the import-time credential
  problem **more carefully than the version drafted here** — it checks whether a password is
  resolvable *including reading `.env`*, where a naive `os.environ.setdefault` would let an env
  var silently outrank a real `.env` password. The duplicate was dropped in favour of #4's.
  *A safety net nobody runs is not a safety net* — and this plan was about to add its net to the
  same invisible directory.
- **🟡 `app/db.py` builds the engine at import time** (`engine = _build_engine()`), so importing
  *any* `app` module demands both DB credentials **and** an installed `psycopg` driver —
  `create_engine()` is lazy about *connecting* but not about *importing the DBAPI*. That is the
  only reason `backend/conftest.py` must inject a fake password to collect the suite. Logged as
  a requirement on the `core/` carve-out in [`MODULES.md`](MODULES.md).
- **🟡 Two `plan_status` vocabularies under one field name.** `fetch_school_plan` emits
  `on_file`/`not_on_file`; the attendance tool computes
  `has_attendance_plan`/`no_attendance_section`/`not_on_file`. Pinned **as-is** (characterization
  ≠ endorsement); unifying it is logged in [`MODULES.md`](MODULES.md) as a post-relocation task.

> **Running them locally:** see `CLAUDE.md` → *Running the tests*. Install the **full**
> `requirements.txt` into a scratch venv, not a hand-picked subset: a minimal venv silently
> under-collects and still reports green (it read 81 passing where CI ran 116). **CI is the
> source of truth.**

### 3.1 — Restructure: `frontend/` + `/api/*` + one image

Repo becomes:

```
school-improvement/
  backend/     FastAPI (unchanged responsibilities)
  frontend/    React + Vite + TypeScript
  Dockerfile   multi-stage: node builds frontend → python serves it
```

> #### 🔺 FIRST item of 3.1c — fix the mis-gated reference routes. Do not let this dissolve into the mount rework.
>
> **`/schools` and `/schools/{id}/metrics` ([`main.py`](../backend/app/main.py)) are gated on
> tenancy today.** Both depend on `get_db` → `get_current_tenant`, so both **403 any signed-in
> user without a district** — while their own comment reads *"Public reference read (no RLS) —
> same for every tenant."* This is exactly the lockout §3.2 exists to prevent, already in the
> code. It predates the §3.2 patch, which added the tool to fix it but deliberately did not
> reach across into the mount rework.
>
> **Why deferring is safe — read this before panicking at "known auth bug, deferred":** it
> **fails closed**. It 403s *legitimate* users; it leaks **nothing** to anyone. The blast radius
> is "outside testers can't read public school reference data", not "someone reads another
> district's plans". It is an availability bug wearing an auth bug's clothes.
>
> **⚠️ The two routes are NOT the same fix.** An earlier version of this item said "switch both
> to `get_db_public` + `get_current_principal`". That is **wrong for the second route**, and
> would trade a fail-closed bug for a silent-wrong-answer one:
>
> | Route | What it is | Fix |
> |---|---|---|
> | `/schools` | genuinely public — *"Public reference read (no RLS) — same for every tenant"* | `get_db_public` + `Depends(get_current_principal)`. Trivial. |
> | `/schools/{id}/metrics` | **deliberately tenant-scoped** — *"RLS auto-scopes: public/state rows PLUS only **this** tenant's private rows"* | **Not** `get_db_public` — that would silently drop a district user's private rows. |
>
> The metrics route needs a **third db dependency**: bind the tenant when the principal has one,
> otherwise run unbound (RLS `p_read` admits `visibility='public'` with no tenant, so a public
> reader still gets public rows). Call it `get_db_for_principal` — it is the auth/tenancy split
> from §3.2 carried down to the DB layer, and it is the *only* new design work in this item.
>
> **Test, in the same diff — both halves:**
> 1. a signed-in principal with **no district claim** gets **200** on both routes;
> 2. a principal **with** a district still sees its private rows on `/schools/{id}/metrics`.
>
> (2) is the one that matters: without it, "fixed" means "quietly stopped returning your data".
> Harmless today — every `fact_metric` row is `tenant_id='public'` — which is exactly why it
> would land unnoticed and detonate later, when the first private metric arrives.

- **All API routes move under `/api/*`.** Breaking change; the current `static/index.html`
  calls `/marts/...` and `/chat` and is being replaced anyway, so there is no compatibility
  window to maintain. Do it in one commit.
  > **Do this at the mount, not in the modules.** `app.include_router(x_router, prefix="/api")`
  > is one line per module in `main.py` — no edit to `marts.py` / `chat.py` / `plans.py`, which
  > are the files the reorg is moving. The target layout already makes `main.py` a *"thin
  > composition root: mount each module's router"*, so `/api` is a property of the composition
  > root and the reorg should preserve it. Editing each router's own `prefix=` instead would
  > pick a fight with the reorg for no benefit.
- **`/health` stays outside `/api`** — it's an unauthenticated liveness probe, not an API
  route. It must never require a token.
- **SPA fallback:** mount `frontend/dist/assets`, then a catch-all `GET` returning
  `index.html` for any non-`/api` path. Register the catch-all **last**, and make sure it
  cannot swallow `/api` 404s — an unmatched `/api/foo` must return JSON 404, not the HTML
  shell. (Silently returning HTML to a fetch() is a genuinely nasty debugging session.)
- **No CORS middleware, in either environment.** Dev uses Vite's `server.proxy` to forward
  `/api` → local FastAPI. Prod is one origin. If anyone ever reaches for
  `CORSMiddleware`, the single-origin property has been broken — treat it as a design smell,
  not a fix.
- The frontend calls **relative paths only** (`fetch('/api/...')`). No absolute URLs, no
  `VITE_API_BASE_URL`.

> **Build-context gotcha (this is why the Dockerfile moves).** Today the build context is
> ~~`backend/` and the deploy is `gcloud run deploy --source backend`~~ (**done** — the context
> is now the repo root and the deploy is `--source .`). A multi-stage build that
> compiles `frontend/` **cannot see it** from that context. The Dockerfile moves to the repo
> root and the deploy becomes `--source .` **run from `school-improvement/`** (the repo root —
> `.git` lives there, *not* in the parent `SchoolImprovement/`).

**Ignore files, and the one footgun that matters.** Measured 2026-07-15: the repo is **4.8 MB**;
`California/` is **2.8 GB** but a **sibling outside the repo**, so a root context never sees it
(the `.gitignore` says so itself). Upload size is already fine — the risk is not the raw data.

- **`.gcloudignore` (new, repo root).** The footgun: **when no `.gcloudignore` exists, gcloud
  auto-generates one that honors `.gitignore`. The moment you hand-write one, that stops.** So
  a hand-written file that forgets `node_modules/` will happily upload it once anyone runs
  `npm install`. Make the first line `#!include:.gitignore` (which already covers
  `node_modules`, `dist`, `__pycache__/`, `.venv/`, `.pytest_cache/`), then add `.git/`.
- **`.dockerignore` (new, repo root).** Docker only reads `.dockerignore` **at the context
  root**, so today's [`backend/.dockerignore`](../backend/.dockerignore) goes **inert** the
  moment the context moves — delete it or move its rules up, but don't leave it there looking
  authoritative. The root one must exclude `node_modules/` and `frontend/dist/` (both are built
  *inside* the image) while **keeping `frontend/` source**, which stage 1 needs.
- Excluding `California/` costs nothing as belt-and-braces, but it is **already out of context**
  — don't let its presence in an ignore file imply the raw data was ever a real upload risk.

### 3.2 — Split authentication from tenancy

> ✅ **Shipped in #8**, ahead of the `core/` carve-out — additive, so the move absorbs it as
> content rather than fighting a concurrent edit. Seam, not path: this asserts that *the module
> owning the trust boundary* exposes two dependencies — true whether that file is
> `app/security.py` today or `core/security.py` after.

In [`security.py`](../backend/app/security.py), two dependencies instead of one:

- `get_current_principal` — verify the Identity Platform ID token, return the claims. **Does not**
  require a tenant. This is what public `/api` routes depend on.
- `get_current_tenant` — calls the above, then maps claims → `tenant_id`, 403 if unmapped.
  Unchanged behaviour; keeps guarding `/api/plans/*` and any future private route.

Token verification itself is already correct and needs no change — `verify_firebase_token`
with `aud = GCP_PROJECT` ([`security.py:66`](../backend/app/security.py)) already checks
signature, issuer, audience, and expiry, and 401s rather than falling through.

**Enforce it at the mount, not as middleware.** The requirement is "verified on *every* `/api`
route"; the cleanest mechanism is a **router-level dependency at the composition root**:

```python
app.include_router(marts_router, prefix="/api", dependencies=[Depends(get_current_principal)])
```

- **vs. HTTP middleware:** middleware runs on *every* request, so it needs hand-written path
  matching to skip `/`, `/health`, and the SPA's static assets — and a bug there either locks
  users out of the login page or silently exempts an API route. The dependency has no path
  logic to get wrong.
- **vs. per-route `Depends`:** those can be forgotten on a new route. A router-level dependency
  cannot — a new endpoint in a mounted module is covered by construction.
- It also composes with 3.1c: the **same line** applies the `/api` prefix and the auth gate, in
  the one file the target layout already designates the composition root.

This satisfies the "middleware verifying the Identity Platform ID token on every `/api` route" requirement —
same enforcement point and same guarantee, fewer ways to get it wrong. `/health` stays outside
`/api` and therefore outside the gate, which is what a liveness probe needs.

> ⚠️ **`CLAUDE.md` calls `security.py` part of the frozen `core` contract.** This split is
> therefore its own reviewed piece of work, not something folded into the frontend commit.
> It is additive (the existing `get_current_tenant` signature and semantics survive), which
> is what keeps it safe.

#### Follow-up (logged, pre-decided — execute, don't re-litigate)

**Drop `async` from `get_current_principal` so FastAPI threadpools it.** That is the fix; it
has been decided. Do not reopen the design.

- **The problem:** it's `async def`, but `_verify_identity_token` → `id_token.verify_firebase_token`
  does **blocking network I/O** (fetching Google's signing certs). Blocking work inside an
  `async def` blocks the whole event loop. A plain `def` dependency gets offloaded to a
  threadpool by FastAPI — strictly better, and a two-character diff.
- **Why it's low priority, and why that's not the same as harmless:** `_google_request` is
  module-level and **caches Google's certs across requests**, so the blocking fetch happens on
  cold start and cert rotation — not per request. The event loop stalls rarely, not constantly.
  That's why this was kept out of the §3.2/§3.3 patch (minimal diff on the trust boundary), and
  why it doesn't gate go-live. It is *latency under load*, never a correctness or auth issue.
- **When it lands:** `test_security.py` drives these with `asyncio.run()`; those calls become
  direct calls. Nothing else changes — the dependency contract is identical either way.

### 3.3 — Make `DEV_MODE` unable to reach production

> ✅ **Shipped in #8**, riding along with §3.2 as one pre-`core/` patch.

[`security.py:38`](../backend/app/security.py) trusts an `X-Dev-Tenant` header when
`dev_mode` is on. Behind Cloud Run IAM that's harmless. On the open internet it is **full
tenant impersonation via a request header** — the single worst outcome available in this
cutover.

`DEV_MODE=false` in the deploy command is not sufficient protection, because it's one typo or
one hurried `--set-env-vars` edit away from being true. Make it structural:

- Refuse to start (or hard-refuse the dev path) when `dev_mode` is true **and** a production
  signal is present — `K_SERVICE` is set by Cloud Run, and `instance_connection_name`
  implies a real Cloud SQL instance.
- The failure must be loud at startup, not silent at request time.

### 3.4 — Move Claude spend control into the app

> ✅ **Shipped (#30, 2026-07-16).** `usage_chat_daily` (migration 0005) counts raw tokens at
> (principal, UTC day, model) grain; `app/usage.py` derives dollars and enforces
> `CHAT_DAILY_USER_USD` ($2) + `CHAT_DAILY_GLOBAL_USD` ($20) — 429 over-cap, **503 fails
> closed** if the counter is unreachable. Core-owned by explicit seam decision (the dry run
> for traces storage). §3.6 is now unblocked; its deploy must run migration 0005 first.
> Anthropic/GCP billing alerts below remain a §3.6 human step.

> ⚠️ **`chat.py` belongs to `serving/`, not to this plan** — #6 folded `chat` + `marts` into
> one module, correcting an earlier claim here that go-live owned the file (§2.5). So §3.4 and
> §3.7 need **coordination with whoever relocates `serving/`**, not unilateral edits.
> `tests/test_chat_tools.py` (#8) is the net either way: it pins the tool dispatch and the
> honesty layer, so a spend cap can't quietly reshape a tool result.

[`DEPLOY.md`](../backend/DEPLOY.md) currently says the IAM gate is "how your Claude spend is
controlled." **This plan removes that gate**, and with Cloudflare grey-clouded there is no
edge rate limiter to inherit. So the control has to be rebuilt in-app, in the same change:

- A **per-principal daily cap** on `/api/chat`, keyed on the verified Identity Platform `sub`/`email`
  (never a client-supplied value). Postgres-backed; a small counter table is fine.
- Keep `--max-instances 4` and the existing `MAX_TOKENS = 3000` / `MAX_TOOL_ITERS = 5`
  ceilings in [`chat.py`](../backend/app/chat.py).
- **`/api/plans/extract` is the expensive one** (an Opus call per PDF, minutes long). It is
  an admin path, not a tester path. Keep it on `get_current_tenant` so it stays closed to
  anyone without a mapped district.
- Set **Anthropic auto-reload + a low-balance alert** (already advised in DEPLOY.md) and a
  **GCP billing alert**. Invited testers are trusted-ish, but a runaway loop is not malice.

### 3.5 — Identity Platform provisioning (the long pole)

This is the task that actually decides the go-live date, and it's the one the old plan
listed last. Nothing else here is blocked on it — it blocks *testers*, not code.

- Enable Identity Platform in `school-improvement-501916`; pick providers (email/password is
  enough for testers; add Google sign-in if convenient).
- Add the **Firebase JS SDK** to the SPA for sign-in + token refresh. Attach the ID token as
  `Authorization: Bearer` on every `/api` fetch. Handle 401 → redirect to sign-in.
- **Provisioning:** for public-data testers, no `tenant_id` claim is needed at all — that's
  the whole point of task 3.2. Create users, and set the claim only for district staff who
  will eventually touch `/plans`.
- Add the domain to Identity Platform's **authorized domains** or sign-in will fail on the custom domain
  with a confusing error.

### 3.6 — Domain, then open the gate (last)

**Verified 2026-07-15:** `us-central1` supports managed Cloud Run domain mappings — the
regional `domains.cloudrun.com/v1` endpoint responds (0 mappings today). No Firebase Hosting
substitution needed. Note the GA `gcloud run domain-mappings` command is **Anthos-only**;
managed mappings require `gcloud beta run domain-mappings` (gcloud's own help says so).

Order matters:

1. Deploy with Identity Platform enforced, **still `--no-allow-unauthenticated`**. Verify via
   `gcloud run services proxy` that a request without a token gets 401 and one with a token
   gets 200.
2. Only then `--allow-unauthenticated`, and set `--min-instances 1`.
3. Create the domain mapping; add the CNAME in Cloudflare as **DNS-only (grey cloud)**.
4. Confirm `*.run.app` is still 401-without-token. **It stays reachable** — the domain is
   convenience, Identity Platform is the boundary. If the run.app URL is open, so is the domain.

Full commands: [`backend/DEPLOY.md`](../backend/DEPLOY.md).

#### Accepted limitation: `*.run.app` bypasses Cloudflare — **do not "fix" this**

With Cloudflare reduced to DNS, it is **decorative for security**: anyone who finds the
`run.app` URL skips it entirely, so WAF/caching there protects nothing on its own. That is
**accepted, deliberately**, and the reasoning is what keeps this scaffold boring:

- **Identity Platform token verification in FastAPI is the real perimeter** — signature, expiry, audience,
  claims read server-side only. That is the conventional Cloud Run pattern, and it does not
  care which hostname the request arrived on.
- **Therefore: no load balancer, no ingress restrictions, and no Cloudflare-header-checking
  middleware.** Do not add Cloudflare-dependent logic anywhere in the app. Hardening (custom
  domain via a global LB with internal ingress, or validating a shared header only Cloudflare
  injects) is a **deliberate infra change if we ever want it — never a scaffold feature.**
- **The proxy stays off** (grey cloud) regardless: orange cloud doesn't just forfeit
  protection, it **breaks the domain mapping** — Google's managed cert can't provision when
  Cloudflare hides the CNAME, leaving the mapping pending, Full(strict) at 525, and Flexible in
  a redirect loop against an HTTPS-only origin. There is no working orange-cloud config here.

> The trap this closes: "Cloudflare is in front, so we're covered." **We are not, and we are
> not trying to be.** Identity Platform is the gate, full stop.

### 3.7 — Charts: the Vega-Lite contract

Agent responses become `{ narrative: str, chart_spec: dict | None }`, where `chart_spec` is a
Vega-Lite v5 spec with **inline data only**. A deterministic validator runs before any spec
is returned:

- validate against the Vega-Lite JSON schema;
- **reject any spec containing `url` or a remote data reference** (this is the security-
  relevant one — a model-authored spec must never be able to make the browser fetch);
- whitelist encoding field names against the scoped semantic-layer field list (stub as a
  config file if the layer isn't queryable yet — **the enforcement point must exist now**);
- cap inline data at 5,000 rows;
- **invalid spec → return narrative only, log the rejection. Never repair or sanitize a
  failed spec into a valid one.** Repair is how a rejected spec quietly becomes a shipped
  one.

Frontend renders with `react-vega`, actions disabled, one chart per response block, charts
independent. Per `CLAUDE.md` module rules this validator is a module boundary — it does not
belong inside `chat.py`.

---

## 4. Sequencing

The safety ordering is the one that matters: **the gate opens last.**

```
DONE (merged) ──────────────────────────────────────────────────────
  3.0 chat characterization tests   #8
  3.2 auth/tenancy split            #8
  3.3 DEV_MODE lockout              #8

PARALLEL — no reorg collision (new files, or deploy-only):
  3.1a frontend/ scaffold ─┬─ 3.5 Identity Platform sign-in in the SPA ──┐
  3.1b Dockerfile → root ──┘                                │
                                                            │
COORDINATE with serving/ (the reorg owns chat.py now):      │
  3.4 chat spend cap  ✅ SHIPPED #30 ─────────────────────────┤
  3.7 charts + validator                                     │
                                                             │
BLOCKED on a human decision:                                 │
  3.1c /api prefix ── needs the frontend call (§2.5) ────────┼─ 3.6 domain + OPEN GATE
                                                            ─┘
```

**3.6 is last, and every hard prerequisite has now shipped.** §3.3 shipped, so tenant
impersonation is closed; but opening the gate before the spend cap still exposes the Anthropic
balance, and that is not recoverable by "we'll add it next week."

**The critical path to "others can play" is §3.5 (Identity Platform), not the code.** `identitytoolkit`
isn't even enabled on the project yet, and it gates *testers*, not commits — so start it early
and in parallel; nothing else waits on it.

**§3.1c is blocked on a decision, not on work.** See the open question in §2.5.

## 5. Cost delta

| Item | Before | After |
|---|---|---|
| Cloud Run | ~$0–5 (`min-instances 0`) | **~$6–15** (`min-instances 1`, always warm) |
| Cloudflare | Pages, free | **$0** — DNS only |
| Cloud Run domain mapping | — | **$0** |
| Identity Platform | ~$0 | **~$0** (well under free-tier MAU) |
| Cloud SQL | ~$10–25 | unchanged |
| Claude API | usage-based, IAM-capped | **usage-based, app-capped** ($20/day global, task 3.4 ✅) |
| **Total (excl. Claude)** | ~$15–35/mo | **~$20–45/mo** |

## 6. Open questions

- **Which domain/subdomain?** A **subdomain** (`app.example.com` → CNAME
  `ghs.googlehosted.com`) is the clean path. An apex domain needs A/AAAA records instead, and
  Cloudflare's CNAME flattening interacts badly with grey-cloud + Google-managed certs.
- **Domain ownership must be verified** in Google Search Console before the mapping will
  create. One-time, but it's a hard prerequisite people forget.
- **Cert provisioning takes up to a few hours** and requires the record to stay **grey**.
  Turning the orange cloud on breaks Google's validation — and it's the exact thing someone
  "helpfully" does when the site looks slow.
- **What replaces `static/index.html`?** Recommend porting it as the first Vite view rather
  than redesigning — it already works, and mixing a port with a redesign makes any regression
  impossible to attribute.
