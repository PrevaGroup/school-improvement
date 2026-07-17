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
    # Require the plan's own metric TEXT to corroborate attendance. A bare proposed_metric_id
    # can be a model mislabel (e.g. a Sense-of-Belonging goal tagged chronic_absenteeism), and
    # trusting it alone was sweeping non-attendance goals into the filter — so we don't anymore.
    return _hit(ml.get("raw_metric_text"))


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
        # shared actions into the attendance response — a single-topic attendance goal still sweeps.
        # (The earlier `g_direct = _hit(statement)` alternative dropped the whole goal when its
        # statement lacked an attendance keyword, which HID a real attendance target; keeping g_att
        # here surfaces the target even with zero counted actions — see the Wilson HS case and
        # docs/design/plan-relevance-tagging.md.)
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
    # Roster is driven by dim_school (the dense, complete spine — every school exists here),
    # with the SIP as OPTIONAL enrichment via LEFT JOIN LATERAL (latest plan per school, or
    # nulls). NEVER gate the roster on plan presence: at CA scale most schools have no
    # extracted SIP, and a school must still appear with its metrics + peers. `has_plan`
    # (below) lets the diagnostic + UI treat a missing plan as a data gap, not a finding.
    rows = db.execute(
        text(
            "SELECT s.school_id, s.school_name, s.school_level, s.district_name, "
            "       s.enroll_total, s.pct_sed, s.pct_el, s.pct_swd, s.locale, "
            "       pe.plan_id, pe.plan_year, pe.document "
            "FROM dim_school s "
            "LEFT JOIN LATERAL ("
            "    SELECT plan_id, plan_year, document FROM plan_extraction "
            "    WHERE school_id = s.school_id ORDER BY plan_year DESC NULLS LAST LIMIT 1"
            ") pe ON true "
            # CAST the optional param: a bare ":lvl IS NULL" is untyped and pg8000
            # (the Cloud SQL Connector driver) rejects it — 42P18 "could not determine
            # data type of parameter". psycopg2 tolerates it; the connector does not.
            "WHERE s.district_id = :d AND (CAST(:lvl AS text) IS NULL OR s.school_level = :lvl) "
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
            "district_name": r["district_name"],
            # Peer-match features (what "schools like you" is computed from) — shown under the title.
            "enroll_total": r["enroll_total"],
            "pct_sed": float(r["pct_sed"]) if r["pct_sed"] is not None else None,
            "pct_el": float(r["pct_el"]) if r["pct_el"] is not None else None,
            "pct_swd": float(r["pct_swd"]) if r["pct_swd"] is not None else None,
            "locale": r["locale"],
            "has_plan": r["plan_id"] is not None,
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
# fact_metric; the matching engine (likeschools/) has no read access to outcomes,
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
            "       s.pct_sed, s.pct_el, s.pct_swd, s.locale "
            "FROM mart_school_peer p JOIN dim_school s ON s.school_id = p.peer_school_id "
            "WHERE p.school_id = :sid AND p.school_year = :yr AND p.rank <= :k ORDER BY p.rank"
        ),
        {"sid": school_id, "yr": yr, "k": k},
    ).mappings().all()
    # Attach each peer's chronic-absenteeism rate — DISPLAY ONLY. The matching stays
    # outcome-free (D1); this is just context so "similar schools, different outcomes" shows.
    peer_ids = [p["peer_school_id"] for p in peers]
    chronic: dict[str, tuple[float, str]] = {}
    if peer_ids:
        stmt = text(
            "SELECT f.school_id, f.value, dp.school_year "
            "FROM fact_metric f JOIN dim_period dp ON f.period_id = dp.period_id "
            "WHERE f.metric_id = :m AND f.student_group_id = 'all' AND f.value IS NOT NULL "
            "AND f.school_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        for r in db.execute(stmt, {"m": ATT_METRIC, "ids": peer_ids}).mappings():
            cur = chronic.get(r["school_id"])
            y = r["school_year"] or ""
            if cur is None or y > cur[1]:
                chronic[r["school_id"]] = (float(r["value"]), y)
    # Which peers have an extracted SIP on file (so the user can spot ones to pull a plan for).
    with_plan: set[str] = set()
    if peer_ids:
        with_plan = set(db.execute(
            text("SELECT school_id FROM plan_extraction WHERE school_id IN :ids").bindparams(
                bindparam("ids", expanding=True)),
            {"ids": peer_ids},
        ).scalars().all())
    peers_out = []
    for p in peers:
        d = dict(p)
        ch = chronic.get(p["peer_school_id"])
        d["chronic_absenteeism_rate"] = ch[0] if ch else None
        d["has_plan"] = p["peer_school_id"] in with_plan
        peers_out.append(d)
    return {
        "school_id": school_id,
        "school_name": self_row["school_name"] if self_row else None,
        "school_level": self_row["school_level"] if self_row else None,
        "school_year": yr,
        "peer_count": len(peers),
        "peers": peers_out,
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
        return {"error": "no peer set for this school (run likeschools.build_peers)"}
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
    # COHORT framing (product decision): the school is ranked WITHIN its similar-schools
    # band, so the distribution AND percentile INCLUDE the school itself (n = peers + 1).
    # Note: the "schools like this one" LIST stays peers-only — a school isn't its own
    # neighbor — but the band it is *ranked within* does include it (CA similar-schools
    # convention). So mart_school_peer holds the neighbors; the cohort is neighbors + self.
    cohort_vals = sorted(
        [latest[p][0] for p in peers if p in latest] + ([target[0]] if target else [])
    )
    direction = db.execute(text("SELECT direction FROM dim_metric WHERE metric_id = :m"), {"m": metric_id}).scalar()

    distribution = None
    percentile = None
    if cohort_vals:
        distribution = {
            "n": len(cohort_vals), "min": cohort_vals[0], "p25": _pctile(cohort_vals, 25),
            "median": _pctile(cohort_vals, 50), "p75": _pctile(cohort_vals, 75), "max": cohort_vals[-1],
        }
        if target:
            # Midrank percentile within the band (strictly-below + half of ties), so a lone
            # extreme reads as ~99th, not exactly 100th — it isn't "worse than itself".
            below = sum(1 for v in cohort_vals if v < target[0])
            equal = sum(1 for v in cohort_vals if v == target[0])
            percentile = round(100 * (below + 0.5 * equal) / len(cohort_vals), 1)
    # Direction-adjusted so higher ALWAYS means "doing better than the band" — the raw
    # percentile (rank in the band) reverses meaning for lower_better metrics.
    performance = None
    if percentile is not None and direction in ("higher_better", "lower_better"):
        performance = round(100 - percentile if direction == "lower_better" else percentile, 1)
    return {
        "school_id": school_id, "metric_id": metric_id, "direction": direction, "school_year": yr,
        "target_value": target[0] if target else None, "target_year": target[1] if target else None,
        "peer_distribution": distribution,               # n = band size (peers + this school)
        "target_percentile_in_band": percentile,         # midrank of the school within its band
        "peer_performance_percentile": performance,      # direction-applied: higher = better than band
    }


# --------------------------------------------------------------------------- #
# Subgroup breakdown — the same metric disaggregated by student group.
# fact_metric is already loaded at the school × period × metric × GROUP grain
# (etl.ca._shared.load_metric_file writes every mapped ReportingCategory), so
# this just stops filtering to student_group_id='all' and returns the fan-out.
# --------------------------------------------------------------------------- #
def fetch_metric_by_subgroup(
    db: Session, school_id: str, metric_id: str = ATT_METRIC, school_year: str | None = None
) -> dict:
    """One school's metric disaggregated by student group (race, gender, EL, SWD, SES, ...).

    Returns every student group that has a row for the latest year the metric is present, each
    with its value, `value_status`, n_size, and `gap_vs_all` (subgroup − All Students, raw). A
    suppressed/absent value is UNKNOWN (small-n privacy suppression), never 0 — `value_status`
    says which, mirroring the DATA HONESTY contract the chat layer enforces.
    """
    meta = db.execute(
        text("SELECT display_name, direction, unit FROM dim_metric WHERE metric_id = :m"),
        {"m": metric_id},
    ).mappings().first()
    if not meta:
        return {"error": f"unknown metric_id '{metric_id}'"}
    # Latest year this metric actually reports a value at this school (subgroups share the period).
    yr = school_year or db.execute(
        text(
            "SELECT max(p.school_year) FROM fact_metric f JOIN dim_period p ON f.period_id = p.period_id "
            "WHERE f.school_id = :s AND f.metric_id = :m AND f.value IS NOT NULL"
        ),
        {"s": school_id, "m": metric_id},
    ).scalar()
    if not yr:
        return {
            "school_id": school_id, "metric_id": metric_id, "display_name": meta["display_name"],
            "direction": meta["direction"], "school_year": None, "subgroups": [],
            "note": "no data for this metric at this school (may not be collected at this level, or not loaded yet)",
        }
    rows = db.execute(
        text(
            "SELECT f.student_group_id, g.label, g.dimension, f.value, f.value_status, f.n_size "
            "FROM fact_metric f "
            "JOIN dim_period p ON f.period_id = p.period_id "
            "JOIN dim_student_group g ON g.student_group_id = f.student_group_id "
            "WHERE f.school_id = :s AND f.metric_id = :m AND p.school_year = :y "
            "ORDER BY (g.dimension = 'total') DESC, g.dimension, g.student_group_id"
        ),
        {"s": school_id, "m": metric_id, "y": yr},
    ).mappings().all()
    out = subgroup_slice(rows)
    return {
        "school_id": school_id, "metric_id": metric_id, "display_name": meta["display_name"],
        "direction": meta["direction"], "unit": meta["unit"], "school_year": yr,
        **out,
        "reading": (
            "gap_vs_all is the raw (subgroup − All Students) difference; use `direction` to read "
            "sign (for lower_better metrics a positive gap = the subgroup is doing WORSE). A null "
            "value with value_status 'suppressed' is privacy-withheld for small n — UNKNOWN, not 0."
        ),
    }


def subgroup_slice(rows: list[dict]) -> dict:
    """Shape the per-group fact rows into the subgroup response (pure — no DB).

    Detects the All Students value, then attaches each subgroup's raw `gap_vs_all`. A null value
    (suppressed / not collected) stays null and gets no gap — never coerced to 0, so a
    privacy-withheld group is never read as "zero absenteeism". Extracted from the query so the
    gap/missingness logic is unit-testable without a database (cf. `attendance_slice`).
    """
    all_value = next(
        (float(r["value"]) for r in rows if r["student_group_id"] == "all" and r["value"] is not None),
        None,
    )
    subgroups = []
    for r in rows:
        v = float(r["value"]) if r["value"] is not None else None
        subgroups.append({
            "student_group_id": r["student_group_id"], "label": r["label"], "dimension": r["dimension"],
            "value": v, "value_status": r["value_status"], "n_size": r["n_size"],
            "gap_vs_all": (
                round(v - all_value, 2)
                if v is not None and all_value is not None and r["student_group_id"] != "all"
                else None
            ),
        })
    return {"all_students_value": all_value, "subgroup_count": len(subgroups), "subgroups": subgroups}


@router.get("/subgroup-metrics")
def subgroup_metrics_ep(
    school_id: str,
    metric_id: str = ATT_METRIC,
    db: Session = Depends(get_db_public),
) -> dict:
    """One school's metric disaggregated by student group (default: chronic absenteeism)."""
    return fetch_metric_by_subgroup(db, school_id, metric_id)


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
        has_plan = bool(s.get("has_plan"))

        if not has_plan:
            # No SIP extracted for this school — a DATA GAP, not a finding. Never let
            # absence-of-plan masquerade as "unmet_need": that would falsely accuse the
            # district of ignoring a need we simply haven't read a plan for. `need` (from
            # metrics + peers) is still shown; only the plan-RESPONSE judgment is withheld.
            alignment = "plan_missing"
        elif need == "high" and thin:
            alignment = "unmet_need"     # the flag that matters: big need, no funded response
        elif need in ("high", "moderate") and not thin:
            alignment = "responsive"
        elif thin:
            alignment = "no_response"
        else:
            alignment = "ok"

        out.append({
            "school_id": s["school_id"], "school_name": s["school_name"],
            "district_name": s.get("district_name"),
            "has_plan": has_plan,
            "enroll_total": s.get("enroll_total"), "pct_sed": s.get("pct_sed"),
            "pct_el": s.get("pct_el"), "pct_swd": s.get("pct_swd"), "locale": s.get("locale"),
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

    # plan_missing sorts after the plan-based findings (it's a data gap, not a verdict) but
    # its secondary sort by absenteeism still floats the highest-need unplanned schools up.
    order = {"unmet_need": 0, "no_response": 1, "responsive": 2, "ok": 3, "plan_missing": 4, "unknown": 5}
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


@router.get("/districts")
def districts_ep(db: Session = Depends(get_db_public)) -> dict:
    """Districts with at least one extracted SIP — the demo's selectable districts (so the
    picker surfaces every onboarded district, e.g. Long Beach + Ventura, not just one)."""
    rows = db.execute(
        text(
            "SELECT s.district_id, max(s.district_name) AS district_name, count(*) AS plan_count "
            "FROM plan_extraction pe JOIN dim_school s ON pe.school_id = s.school_id "
            "WHERE s.district_id IS NOT NULL "
            "GROUP BY s.district_id ORDER BY max(s.district_name)"
        )
    ).mappings().all()
    return {"districts": [dict(r) for r in rows]}


# --------------------------------------------------------------------------- #
# Selected-school detail — the headline indicator charts (multi-metric) + the
# FULL plan (every goal/action, not just attendance). Fetched per selected school.
# --------------------------------------------------------------------------- #
INDICATOR_METRICS = [
    ("chronic_absenteeism_rate", "Chronic absenteeism", "lower_better"),
    ("grad_rate_acgr", "Graduation rate", "higher_better"),
    ("college_going_rate", "College-going rate", "higher_better"),
    # CAASPP Smarter Balanced, % Standard Met or Exceeded (all-grades rollup) — loaded
    # 2026-07-16 for 2023-24 + 2024-25. ES/MS schools finally get outcome indicators here;
    # the three above are HS-heavy (grad/college) or climate-side (absenteeism).
    ("ela_met_standard_pct", "ELA standard met (CAASPP)", "higher_better"),
    ("math_met_standard_pct", "Math standard met (CAASPP)", "higher_better"),
]


def fetch_indicators(db: Session, school_id: str) -> list[dict]:
    """Per-school value + peer distribution for the headline indicators (for the charts)."""
    out = []
    for mid, name, direction in INDICATOR_METRICS:
        b = fetch_peer_benchmark(db, school_id, mid)
        out.append({
            "metric_id": mid, "display_name": name,
            "direction": b.get("direction") or direction,
            "target_value": b.get("target_value"), "target_year": b.get("target_year"),
            "peer_distribution": b.get("peer_distribution"),
            "peer_performance_percentile": b.get("peer_performance_percentile"),
        })
    return out


def full_plan_goals(doc: dict) -> list[dict]:
    """EVERY goal + action in the plan document — the full SPSA, not attendance-filtered."""
    goals_out = []
    for g in doc.get("goals", []) or []:
        actions_out = [{
            "action_number": a.get("action_number"),
            "strategy_text": a.get("strategy_text"),
            "budgeted_amount": a.get("budgeted_amount"),
            "funding_source_raw": a.get("funding_source_raw"),
            "provenance": a.get("provenance"),
        } for a in (g.get("actions", []) or [])]
        goals_out.append({
            "goal_number": g.get("goal_number"), "goal_type": g.get("goal_type"),
            "statement": g.get("statement"), "provenance": g.get("provenance"),
            "actions": actions_out,
        })
    return goals_out


def fetch_school_plan(db: Session, school_id: str) -> dict:
    """The FULL plan (every goal + action, any topic) for one school. Shared by the panel and
    the chat's plan tool, so the chat can answer about ELA/math/climate goals, not just
    attendance. `plan_status` keeps missingness explicit: not_on_file != "has no plan"."""
    row = db.execute(
        text("SELECT plan_year, document FROM plan_extraction WHERE school_id = :s "
             "ORDER BY plan_year DESC NULLS LAST LIMIT 1"),
        {"s": school_id},
    ).mappings().first()
    if not row:
        return {"has_plan": False, "plan_status": "not_on_file", "plan_year": None, "goals": []}
    return {"has_plan": True, "plan_status": "on_file", "plan_year": row["plan_year"],
            "goals": full_plan_goals(row["document"] or {})}


@router.get("/school-detail")
def school_detail_ep(school_id: str, db: Session = Depends(get_db_public)) -> dict:
    """Everything the panel needs for ONE school: indicator charts + the full plan."""
    return {"school_id": school_id, "indicators": fetch_indicators(db, school_id),
            "plan": fetch_school_plan(db, school_id)}
