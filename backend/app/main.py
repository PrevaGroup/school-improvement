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
def list_schools(year: str, db: Session = Depends(get_db)) -> list[dict]:
    # Public reference read (no RLS) — same for every tenant.
    rows = db.execute(
        select(DimSchool).where(DimSchool.school_year == year).limit(200)
    ).scalars().all()
    return [
        {"cds": r.school_cds, "name": r.school_name, "district": r.district_name}
        for r in rows
    ]


@app.get("/schools/{cds}/metrics")
def school_metrics(cds: str, year: str, db: Session = Depends(get_db)) -> list[dict]:
    # RLS auto-scopes: public/state rows PLUS only *this* tenant's private rows.
    # No tenant filter in the query — the database enforces it.
    rows = db.execute(
        select(FactMetric).where(
            FactMetric.school_cds == cds, FactMetric.school_year == year
        )
    ).scalars().all()
    return [
        {
            "metric": r.metric_id,
            "group": r.student_group_id,
            "value": float(r.value) if r.value is not None else None,
            "status": r.value_status,
            "visibility": r.visibility,
            "tenant": r.tenant_id,
        }
        for r in rows
    ]
