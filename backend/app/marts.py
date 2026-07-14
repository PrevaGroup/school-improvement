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
    """Pull the attendance-relevant goals + actions (with provenance) from a plan doc.

    Attribution is at the ACTION level: an action joins the attendance response only when the
    action itself is attendance-relevant (its own text or metric link). A goal sweeps in all of
    its actions ONLY when the goal is *dedicated* to attendance — i.e. it is attendance-relevant
    and is NOT a bundled multi-metric goal. Otherwise a bundled Culture/Climate goal (belonging +
    suspension + a real attendance target sharing one set of strategies) would miscount its shared
    PD as an attendance response — the Wilson HS case. The goal still appears with its attendance
    target link surfaced, so a real target (e.g. "raise attendance to 92.2%") is never hidden.

    Stopgap (Phase 0): the keyword regex is doing semantic classification at serving time. The
    durable fix moves this to structured tags produced at extraction — see
    docs/design/plan-relevance-tagging.md.
    """
    goals_out = []
    for g in doc.get("goals", []) or []:
        g_links = g.get("metric_links", []) or []
        g_att_links = [m for m in g_links if _link_is_attendance(m)]
        # The goal is attendance-relevant at all → it appears, and its attendance target shows.
        g_att = _hit(g.get("statement")) or bool(g_att_links)
        # Bundled = the goal also carries non-attendance metrics; such a goal must NOT sweep its
        # shared actions into the attendance response. A single-topic attendance goal still sweeps.
        g_bundled = any(not _link_is_attendance(m) for m in g_links)
        g_sweep = g_att and not g_bundled
        actions_out = []
        for a in g.get("actions", []) or []:
            a_links = a.get("metric_links", []) or []
            a_att = _hit(a.get("strategy_text")) or any(_link_is_attendance(m) for m in a_links)
            if g_sweep or a_att:
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
                "metric_links": g_att_links,
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


# --------------------------------------------------------------------------- #
# "Schools Like You" serving (spec §6). Reads the public peer marts + public
# fact_metric; the matching engine (etl/peers) has no read access to outcomes,
# which enforces D1 (outcomes can't leak into the distance) architecturally.
# --------------------------------------------------------------------------- #
def _latest_peer_year(db: Session, school_id: str) -> str | None:
    return db.execute(
        text("SELECT max(school_year) FROM mart_school_peer WHERE school_id = :s"),
        {"s": school_id},
    ).scalar()


def fetch_like_schools(db: Session, school_id: str, k: int = 50, school_year: str | None = None) -> dict:
    """The ordered peer list for a school (pure lookup)."""
    yr = school_year or _latest_peer_year(db, school_id)
    if not yr:
        return {"school_id": school_id, "peers": [], "note": "no peer set (has the peer batch run?)"}
    self_row = db.execute(
        text("SELECT school_name, district_name, school_level FROM dim_school WHERE school_id = :s"),
        {"s": school_id},
    ).mappings().first()
    peers = db.execute(
        text(
            "SELECT p.rank, p.distance, p.low_confidence, p.level_bucket, p.peer_school_id, "
            "       s.school_name, s.district_name, s.school_level, s.enroll_total, "
            "       s.pct_sed, s.pct_el, s.pct_swd "
            "FROM mart_school_peer p JOIN dim_school s ON s.school_id = p.peer_school_id "
            "WHERE p.school_id = :sid AND p.school_year = :yr AND p.rank <= :k ORDER BY p.rank"
        ),
        {"sid": school_id, "yr": yr, "k": k},
    ).mappings().all()
    return {
        "school_id": school_id,
        "school_name": self_row["school_name"] if self_row else None,
        "school_level": self_row["school_level"] if self_row else None,
        "school_year": yr,
        "peer_count": len(peers),
        "peers": [dict(p) for p in peers],
    }


def _pctile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (q / 100) * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] * (1 - (idx - lo)) + sorted_vals[hi] * (idx - lo)


def fetch_peer_benchmark(db: Session, school_id: str, metric_id: str, school_year: str | None = None) -> dict:
    """Target school's metric value + its peer-group distribution and percentile.

    Guardrail (spec §6): `target_value` is the absolute number and `direction` says which
    way is good, so peer-relative percentile is never shown as the ceiling. (A fixed
    proficiency bar would enrich this once `ref_benchmark` is populated.)
    """
    yr = school_year or _latest_peer_year(db, school_id)
    if not yr:
        return {"error": "no peer set for this school (run etl.peers.build_peers)"}
    peers = db.execute(
        text("SELECT peer_school_id FROM mart_school_peer WHERE school_id = :s AND school_year = :y"),
        {"s": school_id, "y": yr},
    ).scalars().all()
    if not peers:
        return {"error": "no peer set for this school"}

    stmt = text(
        "SELECT f.school_id, f.value, p.school_year "
        "FROM fact_metric f JOIN dim_period p ON f.period_id = p.period_id "
        "WHERE f.metric_id = :m AND f.student_group_id = 'all' AND f.value IS NOT NULL "
        "AND f.school_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    latest: dict[str, tuple[float, str]] = {}
    for r in db.execute(stmt, {"m": metric_id, "ids": list(peers) + [school_id]}).mappings():
        cur = latest.get(r["school_id"])
        y = r["school_year"] or ""
        if cur is None or y > cur[1]:
            latest[r["school_id"]] = (float(r["value"]), y)

    target = latest.get(school_id)
    peer_vals = sorted(latest[p][0] for p in peers if p in latest)
    direction = db.execute(text("SELECT direction FROM dim_metric WHERE metric_id = :m"), {"m": metric_id}).scalar()

    distribution = None
    percentile = None
    if peer_vals:
        distribution = {
            "n": len(peer_vals), "min": peer_vals[0], "p25": _pctile(peer_vals, 25),
            "median": _pctile(peer_vals, 50), "p75": _pctile(peer_vals, 75), "max": peer_vals[-1],
        }
        if target:
            percentile = round(100 * sum(1 for v in peer_vals if v <= target[0]) / len(peer_vals), 1)
    # Direction-adjusted so higher ALWAYS means "doing better than peers" — the raw
    # percentile (% of peers at/below the value) reverses meaning for lower_better metrics.
    performance = None
    if percentile is not None and direction in ("higher_better", "lower_better"):
        performance = round(100 - percentile if direction == "lower_better" else percentile, 1)
    return {
        "school_id": school_id, "metric_id": metric_id, "direction": direction, "school_year": yr,
        "target_value": target[0] if target else None, "target_year": target[1] if target else None,
        "peer_distribution": distribution,
        "target_percentile_in_peers": percentile,       # raw: % of peers at/below the value
        "peer_performance_percentile": performance,      # direction-applied: higher = better than peers
    }


@router.get("/like-schools")
def like_schools_ep(school_id: str, k: int = 50, db: Session = Depends(get_db_public)) -> dict:
    """Schools most demographically similar to `school_id` (default k=50)."""
    return fetch_like_schools(db, school_id, k)


@router.get("/peer-benchmark")
def peer_benchmark_ep(
    school_id: str,
    metric_id: str = "chronic_absenteeism_rate",
    db: Session = Depends(get_db_public),
) -> dict:
    """A school's metric value vs. its peer group (default: chronic absenteeism)."""
    return fetch_peer_benchmark(db, school_id, metric_id)


# --------------------------------------------------------------------------- #
# Attendance diagnostic — NEED (peer-relative) vs. RESPONSE (what the plan funds).
# The evaluative signal that drives the UI: surfaces schools with a glaring
# attendance need AND a thin/absent attendance plan ("unmet_need").
# --------------------------------------------------------------------------- #
def fetch_attendance_diagnostic(
    db: Session,
    district_id: str = "0622500",
    level: str | None = "High",
    metric_id: str = "chronic_absenteeism_rate",
) -> dict:
    plans = fetch_attendance_plans(db, district_id, level)
    out = []
    for s in plans["schools"]:
        goals = s.get("attendance_goals") or []
        actions = [a for g in goals for a in (g.get("actions") or [])]
        budget = sum((a.get("budgeted_amount") or 0) for a in actions)
        bench = fetch_peer_benchmark(db, s["school_id"], metric_id)
        perf = bench.get("peer_performance_percentile")  # higher = better than peers

        if perf is None:
            need = "unknown"
        elif perf < 34:
            need = "high"          # worse than ~2/3 of peers
        elif perf < 67:
            need = "moderate"
        else:
            need = "low"
        thin = len(actions) == 0 or budget < 1

        if need == "high" and thin:
            alignment = "unmet_need"     # the flag that matters: big need, no funded response
        elif need in ("high", "moderate") and not thin:
            alignment = "responsive"
        elif thin:
            alignment = "no_response"
        else:
            alignment = "ok"

        out.append({
            "school_id": s["school_id"], "school_name": s["school_name"],
            "chronic_absenteeism_rate": s.get("chronic_absenteeism_rate"),
            "chronic_absenteeism_year": s.get("chronic_absenteeism_year"),
            "peer_performance_percentile": perf,
            "peer_distribution": bench.get("peer_distribution"),
            "need": need,
            "attendance_action_count": len(actions),
            "attendance_budget": round(budget, 2),
            "alignment": alignment,
            "attendance_goals": goals,
        })

    order = {"unmet_need": 0, "no_response": 1, "responsive": 2, "ok": 3, "unknown": 4}
    out.sort(key=lambda r: (order.get(r["alignment"], 9), -(r["chronic_absenteeism_rate"] or 0)))
    return {"district_id": district_id, "level": level, "school_count": len(out), "schools": out}


@router.get("/attendance-diagnostic")
def attendance_diagnostic_ep(
    district_id: str = "0622500",
    level: str | None = "High",
    db: Session = Depends(get_db_public),
) -> dict:
    """Per-school attendance need vs. plan response, sorted with 'unmet_need' first."""
    return fetch_attendance_diagnostic(db, district_id, level)
