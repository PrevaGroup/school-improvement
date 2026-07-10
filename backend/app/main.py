"""FastAPI surface — typed endpoints only.

Deliberately no raw-SQL tool: the app composes queries and callers pass parameters,
so a GUC-based tenant binding is safe (§10.3, pattern 1). Every route that touches
private data depends on `get_db`, which binds the tenant + turns on RLS.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import DimSchool, FactMetric

app = FastAPI(title="School Improvement Platform API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/schools")
def list_schools(db: Session = Depends(get_db)) -> list[dict]:
    # Public reference read (no RLS) — same for every tenant.
    rows = db.execute(select(DimSchool).limit(200)).scalars().all()
    return [
        {"school_id": r.school_id, "name": r.school_name, "district": r.district_name}
        for r in rows
    ]


@app.get("/schools/{school_id}/metrics")
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
