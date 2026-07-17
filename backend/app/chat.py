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
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db_public
from .security import get_current_principal
from .traces import TraceRecorder, sha256_hex
from .usage import check_spend_caps, record_chat_usage
from .vocab import METRICS
from .marts import (
    LEVEL_TO_CODE,
    SlotSpec,
    SpotlightItem,
    SpotlightSpec,
    WorkspaceSpec,
    default_workspace_spec,
    fetch_attendance_plans,
    fetch_like_schools,
    fetch_metric_by_subgroup,
    fetch_peer_benchmark,
    fetch_school_plan,
    fetch_slot,
    fetch_workspace,
    resolve_spotlight,
)


def _level_default(school_level: str) -> WorkspaceSpec:
    """The seed workspace for a dim_school.school_level (High/Middle/Elementary)."""
    return default_workspace_spec(LEVEL_TO_CODE.get(school_level, "HS"))

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_TOKENS = 3000
MAX_TOOL_ITERS = 5
DISTRICT_ID = "0622500"  # Long Beach Unified (NCES LEAID)

# UI level -> dim_school.school_level (the header offers High/Middle/Primary)
LEVEL_TO_SCHOOL_LEVEL = {"High": "High", "Middle": "Middle", "Primary": "Elementary"}

# The metric vocabulary as the model sees it — built from core's vocab so a metric added
# there (and loaded into fact_metric) becomes chat-visible with no edit here. This replaces
# hardcoded id lists in the tool descriptions, which had already gone stale once (they
# omitted CAASPP ELA/Math when it landed, leaving chat blind to loaded data).
_METRIC_MENU = "; ".join(f"{m['metric_id']} = {m['display_name']}" for m in METRICS)
_METRIC_PARAM_DESC = ("conformed metric id (default chronic_absenteeism_rate). "
                      f"Available: {_METRIC_MENU}.")


def _describe_slot(s: SlotSpec) -> str:
    return f"{s.metric_id} · {s.school_year or 'latest year'} · {s.student_group_id}"


def build_system(ui_level: str, workspace: WorkspaceSpec | None = None) -> str:
    base = _build_system_base(ui_level)
    if workspace is None:
        return base
    # Render the on-screen state so "don't regurgitate the screen" is grounded in what the
    # screen ACTUALLY shows, and so the model doesn't re-set a slot to its current spec.
    # Ids verbatim (no DB here — build_system stays pure; its hash is traced).
    lines = [f"- Slot {i + 1}: {_describe_slot(s)}" for i, s in enumerate(workspace.slots)]
    lines.append("- Subgroup slice: "
                 + (_describe_slot(workspace.subgroup_slice) if workspace.subgroup_slice
                    else "(empty — offer to fill it when a subgroup question comes up)"))
    pins = len(workspace.plan_spotlight.items) if workspace.plan_spotlight else 0
    lines.append(f"- Plan spotlight: {pins} pinned item(s)" if pins else "- Plan spotlight: (none)")
    return (base
            + "\n\nTHE WORKSPACE CURRENTLY SHOWS (already visible to the user — do not restate "
              "these charts' numbers, and do not re-set a slot to the spec it already has):\n"
            + "\n".join(lines))


def _build_system_base(ui_level: str) -> str:
    return f"""You help education staff understand and compare California {ui_level} schools — Long Beach Unified plus other loaded districts (e.g. Ventura Unified): how they plan to improve student attendance (chronic absenteeism), how they perform on state metrics (chronic absenteeism, suspension, graduation, college-going, CAASPP ELA/Math academic outcomes), and how each compares to the demographically-similar "schools like it" statewide.

The user selected the {ui_level} level — keep every answer at the {ui_level} level. Long Beach is the default focus, but you can answer about any loaded district's schools when named (e.g. "Ventura High") — the tools resolve a named school in whatever district it belongs to.

Always call a tool for real data; never invent schools, numbers, budgets, plan text, or peers:
- query_school_attendance_plans — ATTENDANCE goals + funded strategies (budgets, funding sources, verbatim plan text + page cites) for these schools, optionally one school. Use for attendance-specific need/response questions.
- query_school_plan — the FULL SPSA for one school: EVERY goal (ELA, math, EL, culture/climate, college & career, accountability measures) with funded actions, budgets, funding sources and page cites. Use for any question about what the plan says/funds/omits beyond attendance, or to summarize the plan. The workspace only shows a collapsed goal list, so this is how you answer plan detail.
- find_similar_schools — the demographically-matched peer schools (statewide, same level) for a school. Answers "who is X like?".
- compare_to_peers — a school's actual metric value (default: chronic absenteeism; any conformed metric, incl. ela_met_standard_pct / math_met_standard_pct for CAASPP academics) vs its peer-group distribution, with `peer_performance_percentile` where HIGHER always means doing better than peers.
- query_subgroup_metrics — a school's metric DISAGGREGATED BY STUDENT SUBGROUP (race/ethnicity, gender, English learners, students with disabilities, socioeconomically disadvantaged, foster, homeless). Use this for any "by subgroup", equity, or "which groups are behind" question — including ELA/Math outcomes by subgroup; each subgroup carries its `gap_vs_all`.
- set_workspace_slot — CHANGE WHAT THE WORKSPACE CHARTS SHOW: put a metric/year/subgroup into indicator slot 1, 2, or 3 (always All Students) or into the "subgroup_slice" (one specific subgroup). Use this whenever the user asks to see, show, chart, or compare an indicator, a different year, or a subgroup — change the chart, then give a one-line takeaway instead of reciting the numbers (the chart carries them).
- spotlight_plan_items — PIN the plan goals/actions most relevant to what the workspace shows, each with a one-line reason. Reference goals by the `goal_index`/`action_index` fields from query_school_plan output — read the plan first, then pin.
- set_school — switch the whole workspace to a different school (it opens with the default indicators). Use when the user says "let's look at <school>" — for a one-off comparison question, prefer the query tools instead.
- rename_session — give the session (the entry in the left rail) a short, specific title. Call it ONCE, after the first exchange makes the line of inquiry clear (e.g. "Wilson — EL absenteeism gap"), or when the user asks.

WORKSPACE CONTROL: the left panel is a workspace YOU control through those tools. Prefer showing over telling — if a chart can carry the answer, set the slot. Never claim a slot changed unless the tool call succeeded.

Ground every claim in tool output. When comparing performance, lead with the peer-relative finding via `peer_performance_percentile` (e.g. "worse than ~70% of similar schools"), then cite concrete strategies/budgets/quotes.

BE CONCISE, AND DON'T REGURGITATE THE SCREEN. The workspace already shows, for the selected school, its chronic-absenteeism rate, its peer percentile / need, the peer chart, and its plan detail. Do NOT restate those figures or re-list what's already visible — answer the user's actual question with what they can't already see: interpretation, comparison, the specific plan action / quote they asked about, or the reasoning. Keep answers short (a few sentences or a tight list); expand only when asked. Use light Markdown (bold for key terms, short bullet lists) — not big headings.

DATA HONESTY — absence of data is NOT absence of the thing. This is critical: education data is full of gaps, and treating a gap as a fact produces false, unfair claims about real schools.
- Respect the `plan_status` on each school and the `coverage` block:
  - `not_on_file` → the school's SPSA has not been extracted/loaded YET. Say "I don't have <school>'s plan on file yet" and that its attendance planning is unknown. NEVER say the school "has no attendance plan / no goals / no funded strategies / no accountability" — that is false and defamatory.
  - `no_attendance_section` → the plan IS on file but funds no attendance action. THIS is a real, reportable finding.
  - `has_attendance_plan` → cite its goals, budgets, and quotes.
- A missing/null metric value is UNKNOWN (it may be privacy-suppressed for small enrollment) — never report it as 0 or "none".
- Metrics (chronic absenteeism, peer percentile) are densely covered — state them confidently. Plan detail is sparse — be explicit only when a claim depends on a plan you don't have.
- Never infer that a school lacks a policy, goal, action, or outcome from missing data.

If asked about something outside school plans, state metrics (attendance, discipline, graduation, college-going, CAASPP ELA/Math), or peer comparison, say this prototype covers those for the loaded California districts."""


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
            "peer_performance_percentile (higher = better than peers). Works for any "
            "conformed metric — attendance, discipline, graduation, college-going, and "
            "academic outcomes (CAASPP ELA/Math % standard met)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "school_name": {"type": "string", "description": "the school, by (partial) name."},
                "metric_id": {"type": "string", "description": _METRIC_PARAM_DESC},
            },
            "required": ["school_name"],
        },
    },
    {
        "name": "query_school_plan",
        "description": (
            "The FULL SPSA for ONE school — EVERY goal (any topic: ELA, math, English learners, "
            "culture/climate, college & career, accountability measures) with its funded actions, "
            "budgeted amounts, funding sources and page cites. Use this for ANY question about what "
            "the plan says, funds, or omits beyond attendance — e.g. 'what does the plan fund for "
            "math?', 'which goals have no budget?', 'what are the college-readiness actions?', "
            "'summarize the plan'. For attendance-specific questions prefer "
            "query_school_attendance_plans (it adds the attendance need/response framing)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "school_name": {"type": "string", "description": "the school, by (partial) name, e.g. 'Reid'."},
            },
            "required": ["school_name"],
        },
    },
    {
        "name": "query_subgroup_metrics",
        "description": (
            "One school's metric BROKEN DOWN BY STUDENT SUBGROUP — race/ethnicity, "
            "gender, English learners, students with disabilities, socioeconomically "
            "disadvantaged, foster, homeless, migrant. Returns each subgroup's value, its "
            "gap vs. All Students, and value_status (a suppressed value is privacy-withheld for "
            "small n — UNKNOWN, not 0). Use this for 'attendance for X by subgroup', 'which "
            "groups are behind', or any equity/disaggregation question — including academic "
            "outcomes (CAASPP ELA/Math % standard met) by subgroup."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "school_name": {"type": "string", "description": "the school, by (partial) name, e.g. 'Reid'."},
                "metric_id": {"type": "string", "description": _METRIC_PARAM_DESC},
            },
            "required": ["school_name"],
        },
    },
    # --- workspace tools (docs/design/agentic-workspace-and-sessions.md) ---------------- #
    # These emit a validated SPEC; the server fetches the data and the SAME payload goes to
    # both the model and the UI, so the screen can never show a number the model invented.
    {
        "name": "set_workspace_slot",
        "description": (
            "Change what one workspace chart shows for the SELECTED school. Slots 1-3 are the "
            "indicator charts (always All Students); 'subgroup_slice' is the fourth chart and "
            "takes ONE specific student subgroup. The chart shape never changes — you choose "
            "the metric, the school year, and (for the slice) the subgroup. Returns the "
            "chart-ready data: the school's value vs. its demographic peer band. Use whenever "
            "the user asks to see/show/chart/compare an indicator, year, or subgroup."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot": {"enum": [1, 2, 3, "subgroup_slice"],
                         "description": "which chart to set: 1, 2, 3, or 'subgroup_slice'."},
                "metric_id": {"type": "string", "description": (
                    # Dynamic menu (#50) so a newly-loaded metric is offered here with no edit;
                    # slots chart PERCENT metrics only (the fixed 0-100 scale), which the server
                    # enforces — a non-pct id comes back as a corrective error to retry.
                    f"which metric to chart (percent-scale metrics only). Available: {_METRIC_MENU}.")},
                "school_year": {"type": "string", "description": (
                    "optional, '2023-24' format; omit for the latest available year.")},
                "student_group_id": {"type": "string", "description": (
                    "REQUIRED for subgroup_slice (ignored for slots 1-3, which always show "
                    "'all'): e.g. el, swd, sed, foster, homeless, migrant, race_black, "
                    "race_hispanic, race_white, race_asian, gender_f, gender_m.")},
            },
            "required": ["slot", "metric_id"],
        },
    },
    {
        "name": "spotlight_plan_items",
        "description": (
            "Pin the plan goals/actions most relevant to what the workspace currently shows, "
            "each with a one-line reason — they render above the full goal list, attributed to "
            "you. Reference goals by goal_index (and optionally action_indices) exactly as "
            "returned by query_school_plan — call that FIRST and pick from what you read. The "
            "server renders the pinned items from the stored plan; you author only the reason."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "1-5 pinned items.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal_index": {"type": "integer", "description": "0-based, from query_school_plan."},
                            "action_indices": {"type": "array", "items": {"type": "integer"},
                                               "description": "optional: specific actions; omit to pin the whole goal."},
                            "reason": {"type": "string", "description": "one line: why this is relevant to the current indicators."},
                        },
                        "required": ["goal_index", "reason"],
                    },
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "set_school",
        "description": (
            "Switch the whole workspace to a different school (by partial name, any loaded "
            "district, same level). The workspace opens on that school with the default "
            "indicator slots. Use for 'let's look at X instead' — NOT for a one-off question "
            "about another school (use the query tools for that)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "school_name": {"type": "string", "description": "the school, by (partial) name, e.g. 'Jordan'."},
            },
            "required": ["school_name"],
        },
    },
    {
        "name": "rename_session",
        "description": (
            "Rename the current session — the entry for this line of inquiry in the left rail. "
            "Short and specific (max 60 chars), e.g. 'Wilson — EL absenteeism gap'. Call once, "
            "after the first exchange makes the topic clear, or when the user asks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "the new title, max 60 characters."},
            },
            "required": ["title"],
        },
    },
]


class ChatTurn(BaseModel):
    role: str  # 'user' | 'assistant'
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatTurn]
    level: str = "High"  # High | Middle | Primary (from the demo header)
    # Client-generated conversation id, optional — the stateless API can't infer continuity,
    # so traces of one conversation join only if the client says so (eval-trace-system.md §2).
    session_id: str | None = None
    # Workspace context (docs/design/agentic-workspace-and-sessions.md): the session's
    # selected school and the spec of what is currently on screen. Both optional — the
    # pre-workspace client sends neither and everything behaves as before.
    school_id: str | None = None
    workspace: WorkspaceSpec | None = None


# --- trace vocabulary mapping (Anthropic wire format -> neutral, eval-trace-system.md §5) ---
# This mapping is the Anthropic adapter's job, and until the AgentRunner seam lands (phase 5)
# this file IS the Anthropic adapter — so it lives here, NOT in traces.py. Nothing beyond this
# file may see a raw `stop_reason`; the trace schema carries only normalized `stop` values.
ANTHROPIC_STOP_MAP = {
    "tool_use": "tool_use",
    "end_turn": "end",
    "stop_sequence": "end",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


def _norm_stop(stop_reason: str | None) -> str:
    # An unmapped value passes through raw — the trace vocabulary is open, and inventing a
    # neutral name for a stop we've never seen would hide it from the miner.
    return ANTHROPIC_STOP_MAP.get(stop_reason or "", stop_reason or "unknown")


def _norm_usage(u) -> dict:
    return {
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }


# Computed, not hand-bumped (§2): a changed catalog changes the hash, so an eval delta can be
# attributed to a tool-definition change. sort_keys so dict ordering can't fake a change.
TOOL_CATALOG_HASH = sha256_hex(json.dumps(TOOLS, sort_keys=True))


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


class ToolCtx:
    """Per-request mutable context for the workspace tools.

    Carries the session's selected school + on-screen spec IN, and accumulates the turn's
    workspace mutations OUT — chat() serializes it into the response's `workspace` field, so
    the UI applies exactly the payloads the model saw (one round trip, no refetch, and the
    screen can never show a number the server didn't just build)."""

    def __init__(self, school_id: str | None = None, workspace: WorkspaceSpec | None = None):
        self.school_id = school_id
        self.spec = workspace                 # becomes a DEFAULT copy on first mutation
        self.payloads: dict[str, dict] = {}   # "slot_1".."slot_3" / "subgroup_slice" -> chart payload
        self.spotlight: dict | None = None    # resolved spotlight items
        self.school: dict | None = None       # set when set_school ran
        self.session_title: str | None = None  # set when rename_session ran

    def ensure_spec(self, default: WorkspaceSpec) -> WorkspaceSpec:
        # Only hit when the client sent no workspace but a slot tool ran — seed from the
        # caller's level-appropriate default, then the tool overwrites the touched slot.
        if self.spec is None:
            self.spec = default.model_copy(deep=True)
        return self.spec

    @property
    def mutated(self) -> bool:
        return bool(self.payloads or self.spotlight is not None or self.school is not None
                    or self.session_title is not None)

    def to_response(self) -> dict:
        return {
            "spec": self.spec.model_dump() if self.spec else None,
            "payloads": self.payloads,
            "spotlight": self.spotlight,
            "school": self.school,
            "session_title": self.session_title,
        }


_NO_SCHOOL = ("no school is selected in the workspace — the user must pick a school first, "
              "or use set_school to switch to one by name")


def _run_tool(name: str, ti: dict, db: Session, school_level: str,
              ctx: ToolCtx | None = None) -> dict:
    # `ctx` is keyword-optional so the five original tools keep their pinned 4-arg call
    # shape (tests/test_chat_tools.py characterizes it); only the workspace tools need it.
    if name in ("set_workspace_slot", "spotlight_plan_items", "set_school", "rename_session"):
        return _run_workspace_tool(name, ti, db, school_level, ctx or ToolCtx())
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
    if name == "query_school_plan":
        school = _resolve_school(db, ti.get("school_name"), school_level)
        if not school:
            return {"error": f"no {school_level} school found matching '{ti.get('school_name')}' in the loaded districts"}
        p = fetch_school_plan(db, school["school_id"])
        p["school_name"] = school["school_name"]
        if not p["has_plan"]:
            p["meaning"] = ("no SPSA on file for this school YET — its planning is UNKNOWN, not absent. "
                            "Never report that the school has no plan/goals/actions.")
        return p
    if name == "query_subgroup_metrics":
        school = _resolve_school(db, ti.get("school_name"), school_level)
        if not school:
            return {"error": f"no {school_level} school found matching '{ti.get('school_name')}' in the loaded districts"}
        return fetch_metric_by_subgroup(db, school["school_id"], ti.get("metric_id") or "chronic_absenteeism_rate")
    return {"error": f"unknown tool: {name}"}


def _run_workspace_tool(name: str, ti: dict, db: Session, school_level: str, ctx: ToolCtx) -> dict:
    """The three workspace tools. Every branch: validate the spec server-side, build the
    payload from DB rows, and record the mutation on `ctx` ONLY on success — so the
    response's `workspace` field never carries a slot the model merely attempted."""
    if name == "set_workspace_slot":
        if not ctx.school_id:
            return {"error": _NO_SCHOOL}
        slot = ti.get("slot")
        if isinstance(slot, str) and slot.strip() in ("1", "2", "3"):
            slot = int(slot)
        if slot not in (1, 2, 3, "subgroup_slice"):
            return {"error": "slot must be 1, 2, 3, or 'subgroup_slice'"}
        group = (ti.get("student_group_id") or "all").strip() or "all"
        if slot == "subgroup_slice":
            if group == "all":
                return {"error": ("the subgroup slice shows ONE specific subgroup — pass "
                                  "student_group_id (e.g. 'el', 'swd', 'sed', 'race_hispanic'); "
                                  "slots 1-3 are the All-Students charts")}
        else:
            group = "all"  # the three indicator slots always show All Students
        spec = SlotSpec(metric_id=str(ti.get("metric_id") or ""),
                        school_year=ti.get("school_year") or None,
                        student_group_id=group)
        out = fetch_slot(db, ctx.school_id, spec, school_level)
        if "error" not in out:
            ws = ctx.ensure_spec(_level_default(school_level))
            if slot == "subgroup_slice":
                ws.subgroup_slice = spec
                ctx.payloads["subgroup_slice"] = out
            else:
                ws.slots[slot - 1] = spec
                ctx.payloads[f"slot_{slot}"] = out
        return out

    if name == "spotlight_plan_items":
        if not ctx.school_id:
            return {"error": _NO_SCHOOL}
        plan = fetch_school_plan(db, ctx.school_id)
        if not plan["has_plan"]:
            return {"error": ("no SPSA on file for this school YET — nothing to spotlight. "
                              "Its planning is UNKNOWN, not absent.")}
        try:
            items = [SpotlightItem(**it) for it in (ti.get("items") or [])]
        except (TypeError, ValueError) as e:  # pydantic ValidationError subclasses ValueError
            return {"error": f"bad items shape: {e}"}
        if not items:
            return {"error": "items is required — at least one {goal_index, reason}"}
        resolved = resolve_spotlight(items, plan)
        if not resolved["items"]:
            return {"error": resolved.get("note") or "no valid references"}
        ws = ctx.ensure_spec(_level_default(school_level))
        ws.plan_spotlight = SpotlightSpec(plan_year=plan["plan_year"], items=items)
        ctx.spotlight = resolved
        return resolved

    if name == "set_school":
        school = _resolve_school(db, ti.get("school_name"), school_level)
        if not school:
            return {"error": f"no {school_level} school found matching '{ti.get('school_name')}' in the loaded districts"}
        # Client-side this spawns/activates a session pinned to the school (design § Sessions),
        # so the workspace resets to the level-appropriate defaults; the plan is NOT inlined
        # here — the model reads it via query_school_plan, the UI fetches it on activation.
        ctx.school_id = school["school_id"]
        ctx.spec = _level_default(school_level).model_copy(deep=True)
        ctx.spotlight = None
        ws = fetch_workspace(db, school["school_id"], ctx.spec, include_plan=False)
        ctx.school = dict(school)
        ctx.payloads = {f"slot_{i + 1}": s for i, s in enumerate(ws["slots"])}
        return {"school": dict(school), **ws}

    if name == "rename_session":
        # No school guard — a title is session metadata, not data. The client applies it to
        # the ACTIVE session; the server stores nothing (sessions live in localStorage).
        title = (ti.get("title") or "").strip()
        if not title:
            return {"error": "title is required (max 60 characters)"}
        ctx.session_title = title[:60]
        return {"ok": True, "title": ctx.session_title}

    return {"error": f"unknown workspace tool: {name}"}


@router.post("")
def chat(
    req: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_public),
    principal: dict = Depends(get_current_principal),  # cached — the mount already verified it
) -> dict:
    """Answer a question about Long Beach attendance plans + peer comparison, level-scoped.

    Spend-capped (§3.4): this endpoint pays Anthropic per token, and once the IAM gate opens
    it is the only thing standing between the internet's curiosity and the API bill. The cap
    check runs BEFORE any model call; usage is recorded on every exit path, because tokens
    spent on completed iterations are spent whether or not the last one succeeded.
    """
    # Real tokens always carry `sub` (Firebase sets it); the dev-mode principal doesn't —
    # fall back to its tenant so local RLS testing still gets a stable counter key.
    sub = principal.get("sub") or f"dev:{principal.get(settings.tenant_claim, 'unknown')}"
    check_spend_caps(db, sub)

    messages = [{"role": t.role, "content": t.content} for t in req.messages if t.content.strip()]
    if not messages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no messages")
    ui_level = req.level if req.level in LEVEL_TO_SCHOOL_LEVEL else "High"
    school_level = LEVEL_TO_SCHOOL_LEVEL[ui_level]
    system = build_system(ui_level, req.workspace)
    ctx = ToolCtx(school_id=req.school_id, workspace=req.workspace)

    # Trace the turn (eval-trace-system.md phase 1). Happy paths flush AFTER the response via
    # BackgroundTasks; error paths flush inline before raising, because FastAPI drops the
    # background queue when a handler raises. flush() never raises either way.
    # `workspace` joins the trace envelope only when the client sent one — the key's absence
    # keeps pre-workspace traces (and their pinned assertions) byte-identical.
    ui: dict = {"level": ui_level}
    if req.workspace is not None:
        ui["workspace"] = req.workspace.model_dump()
    recorder = TraceRecorder(
        provider="anthropic", model=settings.chat_model,
        principal_sub=sub, session_id=req.session_id,
        ui=ui,
        versions={"prompt_hash": sha256_hex(system), "tool_catalog_hash": TOOL_CATALOG_HASH},
    )
    question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    recorder.turn_start(question=question, prior_messages=len(messages) - 1,
                        system_hash=sha256_hex(system))

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key_value)
    tools_used: list[str] = []
    resp = None
    hit_max_iters = False
    # Summed across loop iterations (up to MAX_TOOL_ITERS + 1 model calls per user message).
    spent = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    try:
        for i in range(MAX_TOOL_ITERS + 1):
            t0 = time.perf_counter()
            resp = client.messages.create(
                model=settings.chat_model, max_tokens=MAX_TOKENS,
                system=system, tools=TOOLS, messages=messages,
            )
            usage = _norm_usage(resp.usage)
            for k in spent:
                spent[k] += usage[k]
            recorder.model_call(
                iteration=i, stop=_norm_stop(resp.stop_reason), usage=usage,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                content_digest=sha256_hex(
                    "".join(b.text for b in resp.content if b.type == "text")),
            )
            if resp.stop_reason == "refusal":
                reply = "(the assistant declined to answer that.)"
                recorder.turn_end(reply=reply, status="refusal")
                background_tasks.add_task(recorder.flush)
                out = {"reply": reply, "tools_used": tools_used}
                if ctx.mutated:  # slots already changed before the refusal — the UI must know
                    out["workspace"] = ctx.to_response()
                return out
            if resp.stop_reason != "tool_use" or i == MAX_TOOL_ITERS:
                hit_max_iters = resp.stop_reason == "tool_use"
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    tools_used.append(block.name)
                    t0 = time.perf_counter()
                    out = _run_tool(block.name, block.input, db, school_level, ctx=ctx)
                    recorder.tool_call(
                        name=block.name, input=block.input, output=out,
                        error=out.get("error") if isinstance(out, dict) else None,
                        latency_ms=int((time.perf_counter() - t0) * 1000),
                    )
                    results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": json.dumps(out, default=str),
                    })
            messages.append({"role": "user", "content": results})
    except anthropic.APIStatusError as e:
        detail = getattr(e, "message", str(e))
        hint = " → add credits at console.anthropic.com" if "credit balance" in detail.lower() else ""
        recorder.turn_end(reply="", status="error")
        recorder.flush()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"model error {e.status_code}: {detail}{hint}")
    except anthropic.APIConnectionError as e:
        recorder.turn_end(reply="", status="error")
        recorder.flush()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"model connection error: {e}")
    finally:
        if any(spent.values()):
            record_chat_usage(
                db,
                principal_sub=sub,
                principal_email=principal.get("email"),
                model=settings.chat_model,
                **spent,
            )

    reply = "".join(b.text for b in (resp.content if resp else []) if b.type == "text").strip()
    recorder.turn_end(reply=reply, status="max_iters" if hit_max_iters else "ok")
    background_tasks.add_task(recorder.flush)
    out = {"reply": reply or "(no answer produced)", "tools_used": sorted(set(tools_used))}
    if ctx.mutated:
        # The turn's workspace mutations, with the SAME server-built payloads the model saw —
        # the UI applies these directly (one round trip, no refetch, nothing model-authored).
        out["workspace"] = ctx.to_response()
    return out
