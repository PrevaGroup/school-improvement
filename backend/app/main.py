"""FastAPI surface — typed endpoints only.

Deliberately no raw-SQL tool: the app composes queries and callers pass parameters,
so a GUC-based tenant binding is safe (§10.3, pattern 1). Every route that touches
private data depends on `get_db`, which binds the tenant + turns on RLS.
"""
from __future__ import annotations

import pathlib

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .chat import router as chat_router
from .db import get_db
from .marts import router as marts_router
from .models import DimSchool, FactMetric
from .plans import router as plans_router
from .security import assert_dev_mode_not_in_production

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
app.include_router(plans_router, prefix=API)
app.include_router(marts_router, prefix=API)
app.include_router(chat_router, prefix=API)

_STATIC = pathlib.Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the chat UI from the same origin (one Cloud Run service, one IAM gate)."""
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
def health() -> dict:
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
