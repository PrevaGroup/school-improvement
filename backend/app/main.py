"""FastAPI surface — typed endpoints only.

Deliberately no raw-SQL tool: the app composes queries and callers pass parameters,
so a GUC-based tenant binding is safe (§10.3, pattern 1). Every route that touches
private data depends on `get_db`, which binds the tenant + turns on RLS.
"""
from __future__ import annotations

import pathlib

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_proxy import router as auth_proxy_router
from .chat import router as chat_router
from .db import get_db
from .marts import router as marts_router
from .models import DimSchool, FactMetric
from .plans import router as plans_router
from .security import assert_dev_mode_not_in_production, get_current_principal

# Fail the deploy, not the security model: DEV_MODE + a production environment means the
# unverified X-Dev-Tenant header would let any caller impersonate any district. Crash loudly at
# import (= container fails to start) rather than serve a silent impersonation hole.
assert_dev_mode_not_in_production()

app = FastAPI(title="School Improvement Platform API", version="0.1.0")

# Every API route lives under /api — applied HERE, at the composition root, not in each
# router's own `prefix=`. Two reasons:
#
# 1. The modules being relocated (docs/MODULES.md) don't have to be touched to get it, and
#    main.py is already the one file exempt from the module rule.
# 2. It carves the URL space in two, which is what makes the SPA fallback safe. Once the
#    frontend is served from here, the rule is unmissable: /api/* that doesn't match is a
#    JSON 404; anything else is index.html. Share one namespace and a mistyped /marts/typo
#    silently returns an HTML page to a fetch() — `Unexpected token '<'`, no clue why.
#
# /health is deliberately OUTSIDE /api: it's an unauthenticated liveness probe, not an API
# route, and it must never sit behind the auth dependency that /api will gain at go-live.
API = "/api"
# Every mounted /api route requires a VERIFIED, INVITED identity — applied here at the mount,
# not per-route, so a new endpoint in a module is gated by construction and cannot be
# forgotten. get_current_principal = token verified (signature/issuer/audience) AND the email's
# domain is on ALLOWED_EMAIL_DOMAINS. It deliberately does NOT require a tenant — everything
# served today is public data; tenancy stays get_current_tenant's job on the private routes.
# (Middleware was considered and rejected: it needs hand-written path matching to exempt /,
# /health and the SPA assets, and a bug there either locks out the login page or silently
# exempts an API route. A router-level dependency has no path logic to get wrong.)
_REQUIRE_SIGN_IN = [Depends(get_current_principal)]
app.include_router(plans_router, prefix=API, dependencies=_REQUIRE_SIGN_IN)
app.include_router(marts_router, prefix=API, dependencies=_REQUIRE_SIGN_IN)
app.include_router(chat_router, prefix=API, dependencies=_REQUIRE_SIGN_IN)
# Firebase's reserved /__/* namespace, reverse-proxied so sign-in runs on OUR domain
# (custom authDomain — see app/auth_proxy.py). Deliberately UNGATED: it serves the sign-in
# flow to users who don't have a token yet — same access class as /health and the SPA shell.
# Not under /api, not in the route contract (include_in_schema=False), and registered before
# the catch-all below so the SPA fallback never swallows it.
app.include_router(auth_proxy_router)

# The built SPA (frontend/dist), produced by `vite build` in the Dockerfile's node stage and
# copied in beside the app. Absent in a bare dev checkout — see _spa_index below.
_DIST = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"
_SPA_INDEX = _DIST / "index.html"

if (_DIST / "assets").is_dir():
    # Hashed bundles. Mounted, not routed through the catch-all, so a missing asset 404s as an
    # asset instead of silently returning the HTML shell.
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get(f"{API}/me")
def me(principal: dict = Depends(get_current_principal)) -> dict:
    """The invite probe. The SPA's AuthGate calls this once after sign-in, BEFORE loading the
    app: 200 proves the token verifies end-to-end AND the caller is on the invite list; 403
    becomes a clear "not invited" screen instead of a page of scattered fetch errors.

    Returns NOTHING identifying — the 200 itself is the whole signal. The app does not display
    or store the caller's identity (privacy posture 2026-07-17: usage is metered anonymously
    against the opaque `sub`, traces are pseudonymous). `principal` is still verified here; we
    just don't hand the email back to be shown."""
    return {"ok": True}


@app.get(f"{API}/schools")
def list_schools(db: Session = Depends(get_db)) -> list[dict]:
    # Public reference read (no RLS) — same for every tenant.
    rows = db.execute(select(DimSchool).limit(200)).scalars().all()
    return [
        {"school_id": r.school_id, "name": r.school_name, "district": r.district_name}
        for r in rows
    ]


@app.get(f"{API}/schools/{{school_id}}/metrics")
def school_metrics(school_id: str, period_id: str | None = None,
                   db: Session = Depends(get_db)) -> list[dict]:
    # RLS auto-scopes: public/state rows PLUS only *this* tenant's private rows.
    # No tenant filter in the query — the database enforces it.
    stmt = select(FactMetric).where(FactMetric.school_id == school_id)
    if period_id:
        stmt = stmt.where(FactMetric.period_id == period_id)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "metric": r.metric_id,
            "group": r.student_group_id,
            "period": r.period_id,
            "value": float(r.value) if r.value is not None else None,
            "status": r.value_status,
            "visibility": r.visibility,
            "tenant": r.tenant_id,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# The SPA fallback. MUST stay last in this file.
#
# FastAPI matches routes in definition order, so everything above wins first and only genuinely
# unmatched paths reach here. Move this up and it starts eating real routes.
# --------------------------------------------------------------------------- #
@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str) -> FileResponse:
    """Serve the SPA shell so the browser's router can handle client-side routes.

    The `/api` guard is the point of the prefix. Without it, a mistyped `/api/marts/typo` would
    fall through to here and hand an HTML page to a `fetch()` — the caller sees
    `Unexpected token '<'` and no hint that the URL was simply wrong. Unmatched /api paths must
    fail as JSON, like an API.
    """
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such API route: /{full_path}")

    if not _SPA_INDEX.is_file():
        # A dev checkout without `npm run build`. Say so plainly rather than 404 — this is the
        # single most likely local-setup confusion, and a bare 404 sends people hunting routes.
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "frontend not built: run `npm install && npm run build` in frontend/ "
            "(the Docker image builds it automatically)",
        )
    return FileResponse(_SPA_INDEX)
