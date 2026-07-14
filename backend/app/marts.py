"""Plan-content marts — the query surface for the UI.

`GET /marts/attendance-plans` compares how a district's schools plan to address
attendance: for each school it returns the attendance-related goals + funded actions
(with the verbatim plan text / provenance) alongside the school's real chronic-
absenteeism rate. Reads the public `plan_extraction` JSONB + public `fact_metric`, so
NO auth/tenant is needed (SPSAs are public documents).

This is an endpoint-composed mart (MVP); it can be materialized as a table later.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from .db import get_db_public

router = APIRouter(prefix="/marts", tags=["marts"])

ATT_METRIC = "chronic_absenteeism_rate"
ATT_RE = re.compile(r"absent|attendance|chronic|truan", re.I)


def _hit(*texts: str | None) -> bool:
    return any(t and ATT_RE.search(t) for t in texts)


def _link_is_attendance(ml: dict) -> bool:
    return ml.get("proposed_metric_id") == ATT_METRIC or _hit(ml.get("raw_metric_text"))


def attendance_slice(doc: dict) -> list[dict]:
    """Pull the attendance-relevant goals + actions (with provenance) from a plan doc."""
    goals_out = []
    for g in doc.get("goals", []) or []:
        g_links = g.get("metric_links", []) or []
        g_att = _hit(g.get("statement")) or any(_link_is_attendance(m) for m in g_links)
        actions_out = []
        for a in g.get("actions", []) or []:
            a_links = a.get("metric_links", []) or []
            a_att = _hit(a.get("strategy_text")) or any(_link_is_attendance(m) for m in a_links)
            if g_att or a_att:
                actions_out.append({
                    "action_number": a.get("action_number"),
                    "strategy_text": a.get("strategy_text"),
                    "budgeted_amount": a.get("budgeted_amount"),
                    "funding_source_raw": a.get("funding_source_raw"),
                    "provenance": a.get("provenance"),
                })
        if g_att or actions_out:
            goals_out.append({
                "goal_number": g.get("goal_number"),
                "goal_type": g.get("goal_type"),
                "statement": g.get("statement"),
                "provenance": g.get("provenance"),
                "metric_links": [m for m in g_links if _link_is_attendance(m)],
                "actions": actions_out,
            })
    return goals_out


def fetch_attendance_plans(
    db: Session,
    district_id: str = "0622500",
    level: str | None = "High",
) -> dict:
    """Core query: attendance plans across a district's schools (default LB high schools).

    Reusable by both the HTTP route and the chat tool. Public reads only.
    """
    rows = db.execute(
        text(
            "SELECT pe.plan_id, pe.plan_year, pe.document, "
            "       s.school_id, s.school_name, s.school_level "
            "FROM plan_extraction pe JOIN dim_school s ON pe.school_id = s.school_id "
            "WHERE s.district_id = :d AND (:lvl IS NULL OR s.school_level = :lvl) "
            "ORDER BY s.school_name"
        ),
        {"d": district_id, "lvl": level},
    ).mappings().all()

    ids = [r["school_id"] for r in rows if r["school_id"]]
    chronic: dict[str, tuple[float, str]] = {}
    if ids:
        stmt = text(
            "SELECT f.school_id, f.value, p.school_year "
            "FROM fact_metric f JOIN dim_period p ON f.period_id = p.period_id "
            "WHERE f.metric_id = :m AND f.student_group_id = 'all' "
            "AND f.value IS NOT NULL AND f.school_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        for r in db.execute(stmt, {"m": ATT_METRIC, "ids": ids}).mappings():
            cur = chronic.get(r["school_id"])
            yr = r["school_year"] or ""
            if cur is None or yr > cur[1]:
                chronic[r["school_id"]] = (float(r["value"]), yr)

    schools = []
    for r in rows:
        ch = chronic.get(r["school_id"])
        schools.append({
            "school_id": r["school_id"],
            "school_name": r["school_name"],
            "school_level": r["school_level"],
            "plan_year": r["plan_year"],
            "chronic_absenteeism_rate": ch[0] if ch else None,
            "chronic_absenteeism_year": ch[1] if ch else None,
            "attendance_goals": attendance_slice(r["document"] or {}),
        })
    return {"district_id": district_id, "level": level, "school_count": len(schools), "schools": schools}


@router.get("/attendance-plans")
def attendance_plans(
    district_id: str = "0622500",
    level: str | None = "High",
    db: Session = Depends(get_db_public),
) -> dict:
    """Attendance plans across a district's schools (default: Long Beach high schools)."""
    return fetch_attendance_plans(db, district_id, level)
