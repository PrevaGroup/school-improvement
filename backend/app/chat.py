"""Conversational endpoint over the plan + peer marts.

Claude answers questions about how schools plan to improve attendance AND how
each school compares to its demographically-similar peers ("schools like you"), grounded
via inline tools over the public marts. The demo header picks a level (High default);
that scopes every answer server-side. Manual tool-use loop, non-streaming.

Reads only public data, so no tenant/auth here — access is gated at the deploy layer.
Model: `settings.chat_model` (Haiku by default, for cost).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db_public
from .marts import fetch_attendance_plans, fetch_like_schools, fetch_peer_benchmark

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_TOKENS = 3000
MAX_TOOL_ITERS = 5
DISTRICT_ID = "0622500"  # Long Beach Unified (NCES LEAID)

# UI level -> dim_school.school_level (the header offers High/Middle/Primary)
LEVEL_TO_SCHOOL_LEVEL = {"High": "High", "Middle": "Middle", "Primary": "Elementary"}


def build_system(ui_level: str) -> str:
    return f"""You help education staff understand and compare California {ui_level} schools — Long Beach Unified plus other loaded districts (e.g. Ventura Unified): how they plan to improve student attendance (chronic absenteeism), and how each compares to the demographically-similar "schools like it" statewide.

The user selected the {ui_level} level — keep every answer at the {ui_level} level. Long Beach is the default focus, but you can answer about any loaded district's schools when named (e.g. "Ventura High") — the tools resolve a named school in whatever district it belongs to.

Always call a tool for real data; never invent schools, numbers, budgets, plan text, or peers:
- query_school_attendance_plans — attendance goals + funded strategies (budgets, funding sources, verbatim plan text + page cites) for these schools, optionally one school.
- find_similar_schools — the demographically-matched peer schools (statewide, same level) for a school. Answers "who is X like?".
- compare_to_peers — a school's actual metric value (default: chronic absenteeism) vs its peer-group distribution, with `peer_performance_percentile` where HIGHER always means doing better than peers.

Ground every claim in tool output. When comparing performance, lead with the peer-relative finding via `peer_performance_percentile` (e.g. "worse than ~70% of similar schools"), then cite concrete strategies/budgets/quotes.

DATA HONESTY — absence of data is NOT absence of the thing. This is critical: education data is full of gaps, and treating a gap as a fact produces false, unfair claims about real schools.
- Respect the `plan_status` on each school and the `coverage` block:
  - `not_on_file` → the school's SPSA has not been extracted/loaded YET. Say "I don't have <school>'s plan on file yet" and that its attendance planning is unknown. NEVER say the school "has no attendance plan / no goals / no funded strategies / no accountability" — that is false and defamatory.
  - `no_attendance_section` → the plan IS on file but funds no attendance action. THIS is a real, reportable finding.
  - `has_attendance_plan` → cite its goals, budgets, and quotes.
- A missing/null metric value is UNKNOWN (it may be privacy-suppressed for small enrollment) — never report it as 0 or "none".
- Metrics (chronic absenteeism, peer percentile) are densely covered — state them confidently. Plan detail is sparse — be explicit only when a claim depends on a plan you don't have.
- Never infer that a school lacks a policy, goal, action, or outcome from missing data.

If asked about something outside attendance plans or peer comparison, say this prototype covers those for the loaded California districts."""


TOOLS = [
    {
        "name": "query_school_attendance_plans",
        "description": (
            "SPSA plan content about ATTENDANCE / chronic absenteeism: attendance "
            "goals and funded actions (budgeted amounts, funding sources, verbatim plan text + "
            "page cites) alongside each school's chronic-absenteeism rate. Scoped to the "
            "selected level; pass school_name to limit to one school."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "school_name": {"type": "string", "description": "optional: limit to one school by (partial) name, e.g. 'Jordan'."},
            },
        },
    },
    {
        "name": "find_similar_schools",
        "description": (
            "The demographically-similar peer schools (statewide, same instructional level) for "
            "a school — matched on inputs (poverty, EL, disability, size, locale), not "
            "outcomes. Returns ranked peers with name, district, demographics, and distance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "school_name": {"type": "string", "description": "the school, by (partial) name, e.g. 'Wilson'."},
                "k": {"type": "integer", "description": "how many peers to return (default 10)."},
            },
            "required": ["school_name"],
        },
    },
    {
        "name": "compare_to_peers",
        "description": (
            "How a school's metric compares to its demographic peer group: the "
            "school's actual value, the peer distribution (min/p25/median/p75/max), and "
            "peer_performance_percentile (higher = better than peers). Default metric is "
            "chronic_absenteeism_rate; others: suspension_rate, grad_rate_acgr, "
            "college_going_rate, enrollment, stability_rate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "school_name": {"type": "string", "description": "the school, by (partial) name."},
                "metric_id": {"type": "string", "description": "conformed metric id (default chronic_absenteeism_rate)."},
            },
            "required": ["school_name"],
        },
    },
]


class ChatTurn(BaseModel):
    role: str  # 'user' | 'assistant'
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatTurn]
    level: str = "High"  # High | Middle | Primary (from the demo header)


def _resolve_school(db: Session, name: str | None, school_level: str) -> dict | None:
    """Resolve a school by (partial) name + level across ALL loaded districts — not just Long
    Beach. Long Beach wins on ties, so the demo default still applies when a name is ambiguous."""
    if not (name or "").strip():
        return None
    r = db.execute(
        text(
            "SELECT school_id, school_name, district_id FROM dim_school "
            "WHERE school_level = :lv AND school_name ILIKE :n "
            "ORDER BY (district_id = :demo) DESC, school_name LIMIT 1"
        ),
        {"lv": school_level, "n": f"%{name.strip()}%", "demo": DISTRICT_ID},
    ).mappings().first()
    return dict(r) if r else None


def _run_tool(name: str, ti: dict, db: Session, school_level: str) -> dict:
    if name == "query_school_attendance_plans":
        needle = (ti.get("school_name") or "").strip()
        if needle:
            # Named school: resolve it in ANY loaded district, then read that district's roster —
            # so "Ventura High" is found in Ventura Unified, not missed by a Long Beach-only query.
            hit = _resolve_school(db, needle, school_level)
            district_id = hit["district_id"] if hit else DISTRICT_ID
        else:
            district_id = DISTRICT_ID  # no name → the demo default district (Long Beach) roster
        data = fetch_attendance_plans(db, district_id=district_id, level=school_level)
        # Level-wide coverage, computed BEFORE any name filter, so the model knows how much
        # of the plan layer actually exists vs. is just not loaded yet.
        at_level = len(data["schools"])
        on_file = sum(1 for s in data["schools"] if s.get("has_plan"))
        if needle:
            nlow = needle.lower()
            data["schools"] = [s for s in data["schools"] if nlow in (s["school_name"] or "").lower()]
        # Tri-state status per school so the model NEVER reads "no rows" as "no plan exists".
        for s in data["schools"]:
            if not s.get("has_plan"):
                s["plan_status"] = "not_on_file"          # SPSA not extracted/loaded yet — UNKNOWN, not absent
            elif s.get("attendance_goals"):
                s["plan_status"] = "has_attendance_plan"   # plan on file WITH attendance actions
            else:
                s["plan_status"] = "no_attendance_section"  # plan on file, no attendance goal — a REAL finding
        data["school_count"] = len(data["schools"])
        data["coverage"] = {
            "district_id": district_id, "level": school_level,
            "schools_at_level": at_level, "plans_on_file_at_level": on_file,
            "meaning": ("plan_status 'not_on_file' = the school's SPSA has not been extracted/loaded YET, so its "
                        "attendance planning is UNKNOWN — do NOT report it as having no plan/goals/actions. "
                        "'no_attendance_section' = plan IS on file but funds no attendance action (a real finding)."),
        }
        return data
    if name == "find_similar_schools":
        school = _resolve_school(db, ti.get("school_name"), school_level)
        if not school:
            return {"error": f"no {school_level} school found matching '{ti.get('school_name')}' in the loaded districts"}
        return fetch_like_schools(db, school["school_id"], int(ti.get("k") or 10))
    if name == "compare_to_peers":
        school = _resolve_school(db, ti.get("school_name"), school_level)
        if not school:
            return {"error": f"no {school_level} school found matching '{ti.get('school_name')}' in the loaded districts"}
        bench = fetch_peer_benchmark(db, school["school_id"], ti.get("metric_id") or "chronic_absenteeism_rate")
        if isinstance(bench, dict) and bench.get("target_value") is None:
            # A missing metric is UNKNOWN (possibly privacy-suppressed for small enrollment),
            # not zero — say so rather than letting the model infer a value.
            bench["value_status"] = ("this school's value for this metric is not available (it may be "
                                     "privacy-suppressed for small enrollment) — treat as UNKNOWN, never 0.")
        return bench
    return {"error": f"unknown tool: {name}"}


@router.post("")
def chat(req: ChatRequest, db: Session = Depends(get_db_public)) -> dict:
    """Answer a question about Long Beach attendance plans + peer comparison, level-scoped."""
    messages = [{"role": t.role, "content": t.content} for t in req.messages if t.content.strip()]
    if not messages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no messages")
    ui_level = req.level if req.level in LEVEL_TO_SCHOOL_LEVEL else "High"
    school_level = LEVEL_TO_SCHOOL_LEVEL[ui_level]
    system = build_system(ui_level)

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key_value)
    tools_used: list[str] = []
    resp = None
    try:
        for i in range(MAX_TOOL_ITERS + 1):
            resp = client.messages.create(
                model=settings.chat_model, max_tokens=MAX_TOKENS,
                system=system, tools=TOOLS, messages=messages,
            )
            if resp.stop_reason == "refusal":
                return {"reply": "(the assistant declined to answer that.)", "tools_used": tools_used}
            if resp.stop_reason != "tool_use" or i == MAX_TOOL_ITERS:
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    tools_used.append(block.name)
                    out = _run_tool(block.name, block.input, db, school_level)
                    results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": json.dumps(out, default=str),
                    })
            messages.append({"role": "user", "content": results})
    except anthropic.APIStatusError as e:
        detail = getattr(e, "message", str(e))
        hint = " → add credits at console.anthropic.com" if "credit balance" in detail.lower() else ""
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"model error {e.status_code}: {detail}{hint}")
    except anthropic.APIConnectionError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"model connection error: {e}")

    reply = "".join(b.text for b in (resp.content if resp else []) if b.type == "text").strip()
    return {"reply": reply or "(no answer produced)", "tools_used": sorted(set(tools_used))}
