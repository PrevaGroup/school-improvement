"""Characterization tests for `app.chat._run_tool` — the tools the model can call
(five query tools + the three workspace tools of agentic-workspace-and-sessions.md).

**These pin CURRENT behavior, not desired behavior.** They exist so the modular-backend reorg
(`docs/MODULES.md`) can relocate `app/marts.py` out from under `chat` and prove nothing changed.
`chat` is the highest-breakage file in that move — it imports **five** serving functions from
`app.marts` (more than any other consumer) — and until now it had no tests at all.

Deliberately agnostic about where the code lands: whether `marts` splits by feature or `chat`
and the marts fold into one `serving` module, the risk is identical and so is this net. It
pins the *call contract*, not the module map, so it stays valid either way.

`tests/test_route_contract.py` freezes the HTTP surface from the outside; this freezes chat's
*internals* — the dispatch and the honesty layer, neither of which a URL check can see. If a
test here fails after the relocation, the relocation broke chat. That is the whole point.

**No database.** `_run_tool`'s only DB touches are `_resolve_school` and the five `fetch_*`
functions; every test patches all of them, so `db` is an inert sentinel. What's left — and what
these tests actually pin — is the part that would break silently:

  1. **the seam**: which mart function each tool calls, and with exactly which arguments
     (defaults like `k=10` and `metric_id="chronic_absenteeism_rate"` live in chat, not marts);
  2. **the honesty layer**: the `plan_status` / `coverage` / `value_status` / `meaning` fields
     chat bolts onto mart output so the model can never read "no rows" as "no plan exists".

(2) is why this matters beyond the reorg: those fields are the guardrail against the model
making false claims about real schools. A mart change that quietly altered `has_plan` would
corrupt them with no other test to notice.

Run:  python -m pytest tests/test_chat_tools.py -v
"""
import pytest

from app import chat

DB = object()  # inert sentinel — patched-out code never touches it

LB = "0622500"      # Long Beach Unified (NCES LEAID) — chat.DISTRICT_ID, the demo default
VENTURA = "0682670"  # a different loaded district, for the cross-district path


def _school(school_id="060000100001", name="Wilson High", district_id=LB) -> dict:
    return {"school_id": school_id, "school_name": name, "district_id": district_id}


@pytest.fixture
def calls():
    """Records what each patched mart function was called with."""
    return {}


@pytest.fixture
def patch_marts(monkeypatch, calls):
    """Patch every DB-touching name in `app.chat`, recording args and returning canned payloads.

    Patches the names *as chat imported them* (`chat.fetch_like_schools`, not
    `marts.fetch_like_schools`) — chat did `from .marts import ...`, so the module attribute is
    the real seam, and it stays the seam after the reorg rewrites the import's source.
    """
    def _record(name, retval):
        def fake(db, *args, **kwargs):
            calls[name] = {"db": db, "args": args, "kwargs": kwargs}
            return retval() if callable(retval) else retval
        return fake

    def install(*, resolve=None, plans=None, like=None, bench=None, plan=None, subgroup=None,
                slot=None, workspace=None):
        monkeypatch.setattr(chat, "_resolve_school",
                            lambda db, name, lvl: (calls.__setitem__(
                                "_resolve_school", {"name": name, "level": lvl}) or resolve))
        monkeypatch.setattr(chat, "fetch_attendance_plans", _record("fetch_attendance_plans", plans))
        monkeypatch.setattr(chat, "fetch_like_schools", _record("fetch_like_schools", like))
        monkeypatch.setattr(chat, "fetch_peer_benchmark", _record("fetch_peer_benchmark", bench))
        monkeypatch.setattr(chat, "fetch_school_plan", _record("fetch_school_plan", plan))
        monkeypatch.setattr(chat, "fetch_metric_by_subgroup", _record("fetch_metric_by_subgroup", subgroup))
        monkeypatch.setattr(chat, "fetch_slot", _record("fetch_slot", slot))
        monkeypatch.setattr(chat, "fetch_workspace", _record("fetch_workspace", workspace))
    return install


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
def test_unknown_tool_returns_error_not_raise(patch_marts):
    """An unrecognized tool name is reported back to the model, never raised."""
    patch_marts()
    assert _err(chat._run_tool("no_such_tool", {}, DB, "High")) == "unknown tool: no_such_tool"


def _err(out: dict) -> str:
    return out.get("error", "")


@pytest.mark.parametrize("tool", [
    "find_similar_schools", "compare_to_peers", "query_school_plan", "query_subgroup_metrics",
])
def test_unresolved_school_short_circuits_with_error(patch_marts, calls, tool):
    """Every school-scoped tool bails with an error when the name doesn't resolve — and must NOT
    fall through to a mart call with a null school."""
    patch_marts(resolve=None)
    out = chat._run_tool(tool, {"school_name": "Nowhere HS"}, DB, "High")
    assert "no High school found matching 'Nowhere HS'" in _err(out)
    assert not [k for k in calls if k.startswith("fetch_")]  # no mart was called


# --------------------------------------------------------------------------- #
# query_school_attendance_plans — district routing, coverage, tri-state status
# --------------------------------------------------------------------------- #
def _plans_payload(*schools) -> dict:
    return {"district_id": LB, "level": "High", "school_count": len(schools),
            "schools": list(schools)}


def _row(name, has_plan=True, goals=None) -> dict:
    return {"school_name": name, "has_plan": has_plan, "attendance_goals": goals or []}


def test_attendance_plans_without_name_uses_demo_district(patch_marts, calls):
    """No school named → the Long Beach roster, without resolving anything."""
    patch_marts(plans=_plans_payload(_row("Wilson High")))
    chat._run_tool("query_school_attendance_plans", {}, DB, "High")
    assert calls["fetch_attendance_plans"]["kwargs"] == {"district_id": LB, "level": "High"}
    assert "_resolve_school" not in calls  # no name → no lookup at all


def test_attendance_plans_named_school_routes_to_its_own_district(patch_marts, calls):
    """"Ventura High" is found in Ventura Unified, so the roster read is Ventura's — not a
    Long Beach-only query that would miss it."""
    patch_marts(resolve=_school(name="Ventura High", district_id=VENTURA),
                plans=_plans_payload(_row("Ventura High")))
    chat._run_tool("query_school_attendance_plans", {"school_name": "Ventura High"}, DB, "High")
    assert calls["fetch_attendance_plans"]["kwargs"]["district_id"] == VENTURA


def test_attendance_plans_unresolved_name_falls_back_to_demo_district(patch_marts, calls):
    """Unlike the school-scoped tools, this one degrades to the demo district rather than
    erroring — the name filter below then simply yields nothing."""
    patch_marts(resolve=None, plans=_plans_payload(_row("Wilson High")))
    out = chat._run_tool("query_school_attendance_plans", {"school_name": "Nowhere"}, DB, "High")
    assert calls["fetch_attendance_plans"]["kwargs"]["district_id"] == LB
    assert out["schools"] == []          # filtered out by name
    assert out["school_count"] == 0
    assert "error" not in out


def test_attendance_plans_coverage_is_computed_before_the_name_filter(patch_marts):
    """SEMANTIC CONTRACT — the ordering here is deliberate. Do NOT "fix" it.

    `coverage` answers "how much of the plan layer exists at this level?" — NOT "how many rows
    did you return?". So it is computed BEFORE the name filter: 3 schools at level, 2 on file,
    even though the filter leaves a single row.

    It looks inconsistent (coverage says 3, school_count says 1) and that inconsistency is the
    entire point: it's what lets the model distinguish "the plan layer is thin here" from "you
    filtered to one school". Move the computation after the filter to make the numbers "agree"
    and coverage becomes a tautology — always 1-of-1 — and the model loses its only signal that
    data is missing rather than merely unselected. That is precisely the misreading the
    plan_status/coverage honesty layer exists to prevent.
    """
    patch_marts(resolve=_school(name="Wilson High"),
                plans=_plans_payload(_row("Wilson High", goals=[{"g": 1}]),
                                     _row("Poly High", has_plan=True),
                                     _row("Jordan High", has_plan=False)))
    out = chat._run_tool("query_school_attendance_plans", {"school_name": "Wilson"}, DB, "High")
    assert out["coverage"]["schools_at_level"] == 3       # pre-filter
    assert out["coverage"]["plans_on_file_at_level"] == 2  # pre-filter
    assert out["school_count"] == 1                        # post-filter
    assert [s["school_name"] for s in out["schools"]] == ["Wilson High"]
    assert out["coverage"]["district_id"] == LB and out["coverage"]["level"] == "High"


def test_attendance_plans_tri_state_status(patch_marts):
    """The FERPA-adjacent guardrail: absence of data is not absence of the thing.

    not_on_file        → SPSA never extracted; planning UNKNOWN (must never read as "no plan")
    no_attendance_section → plan IS on file but funds no attendance action (a REAL finding)
    has_attendance_plan   → plan on file with attendance goals
    """
    patch_marts(plans=_plans_payload(
        _row("Has Goals", has_plan=True, goals=[{"g": 1}]),
        _row("Plan No Attendance", has_plan=True, goals=[]),
        _row("Not Loaded", has_plan=False),
    ))
    out = chat._run_tool("query_school_attendance_plans", {}, DB, "High")
    status = {s["school_name"]: s["plan_status"] for s in out["schools"]}
    assert status == {
        "Has Goals": "has_attendance_plan",
        "Plan No Attendance": "no_attendance_section",
        "Not Loaded": "not_on_file",
    }
    # The meaning blurb must ship with the data — it's what the model reads to stay honest.
    assert "not_on_file" in out["coverage"]["meaning"]
    assert "UNKNOWN" in out["coverage"]["meaning"]


# --------------------------------------------------------------------------- #
# find_similar_schools
# --------------------------------------------------------------------------- #
def test_find_similar_schools_default_k_is_10(patch_marts, calls):
    """k defaults to 10 *in chat* (marts' own default is 50) — pin it here, since the reorg
    moves the callee and this default would vanish silently."""
    patch_marts(resolve=_school(), like={"peers": []})
    chat._run_tool("find_similar_schools", {"school_name": "Wilson"}, DB, "High")
    assert calls["fetch_like_schools"]["args"] == ("060000100001", 10)


@pytest.mark.parametrize("given,expected", [(5, 5), ("7", 7), (0, 10), (None, 10)])
def test_find_similar_schools_k_coercion(patch_marts, calls, given, expected):
    """`int(ti.get("k") or 10)` — a string k is coerced; 0 and None both fall back to 10."""
    patch_marts(resolve=_school(), like={"peers": []})
    chat._run_tool("find_similar_schools", {"school_name": "Wilson", "k": given}, DB, "High")
    assert calls["fetch_like_schools"]["args"][1] == expected


# --------------------------------------------------------------------------- #
# compare_to_peers — the "missing is not zero" guardrail
# --------------------------------------------------------------------------- #
def test_compare_to_peers_defaults_to_chronic_absenteeism(patch_marts, calls):
    patch_marts(resolve=_school(), bench={"target_value": 25.0})
    chat._run_tool("compare_to_peers", {"school_name": "Wilson"}, DB, "High")
    assert calls["fetch_peer_benchmark"]["args"] == ("060000100001", "chronic_absenteeism_rate")


def test_compare_to_peers_honors_explicit_metric(patch_marts, calls):
    patch_marts(resolve=_school(), bench={"target_value": 90.0})
    chat._run_tool("compare_to_peers", {"school_name": "Wilson", "metric_id": "graduation_rate"},
                   DB, "High")
    assert calls["fetch_peer_benchmark"]["args"][1] == "graduation_rate"


def test_compare_to_peers_missing_value_is_marked_unknown_not_zero(patch_marts):
    """A null target_value gets an explicit UNKNOWN note (it may be privacy-suppressed for small
    enrollment). Without this the model can infer 0 — a false claim about a real school."""
    patch_marts(resolve=_school(), bench={"target_value": None, "peer_performance_percentile": None})
    out = chat._run_tool("compare_to_peers", {"school_name": "Wilson"}, DB, "High")
    assert "UNKNOWN, never 0" in out["value_status"]
    assert "privacy-suppressed" in out["value_status"]


def test_compare_to_peers_present_value_gets_no_unknown_note(patch_marts):
    """The note is injected only when the value is genuinely missing — a real value stays clean."""
    patch_marts(resolve=_school(), bench={"target_value": 25.0, "peer_performance_percentile": 30})
    out = chat._run_tool("compare_to_peers", {"school_name": "Wilson"}, DB, "High")
    assert "value_status" not in out
    assert out["target_value"] == 25.0


# --------------------------------------------------------------------------- #
# query_school_plan
# --------------------------------------------------------------------------- #
def test_query_school_plan_attaches_resolved_name(patch_marts, calls):
    """marts returns the plan keyed by id; chat adds the human name it resolved."""
    patch_marts(resolve=_school(name="Wilson High"),
                plan={"has_plan": True, "plan_status": "on_file", "plan_year": "2024-25", "goals": []})
    out = chat._run_tool("query_school_plan", {"school_name": "Wilson"}, DB, "High")
    assert out["school_name"] == "Wilson High"
    assert calls["fetch_school_plan"]["args"] == ("060000100001",)
    assert "meaning" not in out  # plan exists → no missingness blurb


def test_query_school_plan_missing_plan_gets_meaning_blurb(patch_marts):
    """has_plan False → an explicit "UNKNOWN, not absent" note for the model."""
    patch_marts(resolve=_school(),
                plan={"has_plan": False, "plan_status": "not_on_file", "plan_year": None, "goals": []})
    out = chat._run_tool("query_school_plan", {"school_name": "Wilson"}, DB, "High")
    assert "UNKNOWN, not absent" in out["meaning"]
    assert "Never report that the school has no plan" in out["meaning"]


def test_query_school_plan_status_vocabulary_differs_from_attendance_tool(patch_marts):
    """CHARACTERIZATION OF AN INCONSISTENCY, not an endorsement.

    `fetch_school_plan` emits plan_status 'on_file'/'not_on_file', while the attendance tool
    computes its own 'has_attendance_plan'/'no_attendance_section'/'not_on_file'. Two tools,
    two vocabularies, same field name — pinned so a reorg doesn't accidentally "fix" or
    entrench it silently. If it gets unified later, this test SHOULD fail and be updated.
    """
    patch_marts(resolve=_school(),
                plan={"has_plan": True, "plan_status": "on_file", "plan_year": "2024-25", "goals": []})
    out = chat._run_tool("query_school_plan", {"school_name": "Wilson"}, DB, "High")
    assert out["plan_status"] == "on_file"  # NOT "has_attendance_plan"


# --------------------------------------------------------------------------- #
# query_subgroup_metrics
# --------------------------------------------------------------------------- #
def test_query_subgroup_metrics_defaults_to_chronic_absenteeism(patch_marts, calls):
    patch_marts(resolve=_school(), subgroup={"subgroups": []})
    chat._run_tool("query_subgroup_metrics", {"school_name": "Wilson"}, DB, "High")
    assert calls["fetch_metric_by_subgroup"]["args"] == ("060000100001", "chronic_absenteeism_rate")


def test_query_subgroup_metrics_passes_through_unchanged(patch_marts):
    """chat adds nothing here — the subgroup payload (incl. gap_vs_all) is marts' contract.
    Pinned so the reorg can't quietly start reshaping it in transit."""
    payload = {"all_students_value": 20.0, "subgroup_count": 2, "subgroups": [{"gap_vs_all": 12.0}]}
    patch_marts(resolve=_school(), subgroup=payload)
    assert chat._run_tool("query_subgroup_metrics", {"school_name": "Wilson"}, DB, "High") is payload


# --------------------------------------------------------------------------- #
# workspace tools (docs/design/agentic-workspace-and-sessions.md) — Claude controls
# a SPEC, the server renders the DATA. What these pin: (1) the no-school guard,
# (2) the slots-1-3-are-always-All-Students rule vs. the slice-needs-a-subgroup rule
# (both live in chat, not marts), and (3) that ctx records a mutation ONLY on
# success — the response's workspace field must never carry an attempted slot.
# --------------------------------------------------------------------------- #
def _ctx(school_id="060000100001") -> "chat.ToolCtx":
    return chat.ToolCtx(school_id=school_id)


@pytest.mark.parametrize("tool,ti", [
    ("set_workspace_slot", {"slot": 1, "metric_id": "suspension_rate"}),
    ("spotlight_plan_items", {"items": [{"goal_index": 0, "reason": "r"}]}),
])
def test_workspace_tools_require_a_selected_school(patch_marts, calls, tool, ti):
    patch_marts()
    out = chat._run_tool(tool, ti, DB, "High", ctx=chat.ToolCtx())
    assert "no school is selected" in _err(out)
    assert not [k for k in calls if k.startswith("fetch_")]


def test_set_workspace_slot_records_spec_and_payload_on_success(patch_marts, calls):
    payload = {"slot_spec": {"metric_id": "suspension_rate"}, "target_value": 12.0}
    patch_marts(slot=payload)
    ctx = _ctx()
    out = chat._run_tool("set_workspace_slot",
                         {"slot": 2, "metric_id": "suspension_rate", "school_year": "2022-23"},
                         DB, "High", ctx=ctx)
    assert out is payload
    school_id, spec, level = calls["fetch_slot"]["args"]
    assert school_id == "060000100001"
    assert (spec.metric_id, spec.school_year, spec.student_group_id) == \
        ("suspension_rate", "2022-23", "all")
    assert level == "High"
    assert ctx.spec.slots[1].metric_id == "suspension_rate"   # slot 2 -> index 1
    assert ctx.payloads["slot_2"] is payload
    assert ctx.mutated


def test_set_workspace_slot_untouched_slots_keep_the_default(patch_marts):
    """Setting one slot must not clobber the others — they stay on the default spec."""
    patch_marts(slot={"ok": True})
    ctx = _ctx()
    chat._run_tool("set_workspace_slot", {"slot": 2, "metric_id": "suspension_rate"},
                   DB, "High", ctx=ctx)
    defaults = chat.DEFAULT_WORKSPACE_SPEC.slots
    assert ctx.spec.slots[0].metric_id == defaults[0].metric_id
    assert ctx.spec.slots[2].metric_id == defaults[2].metric_id


def test_slots_1_to_3_always_show_all_students(patch_marts, calls):
    """A subgroup on an indicator slot is silently normalized to 'all' — the slice is the
    one chart that takes a subgroup."""
    patch_marts(slot={"ok": True})
    chat._run_tool("set_workspace_slot",
                   {"slot": 1, "metric_id": "chronic_absenteeism_rate", "student_group_id": "el"},
                   DB, "High", ctx=_ctx())
    assert calls["fetch_slot"]["args"][1].student_group_id == "all"


def test_subgroup_slice_requires_a_specific_subgroup(patch_marts, calls):
    patch_marts(slot={"ok": True})
    out = chat._run_tool("set_workspace_slot",
                         {"slot": "subgroup_slice", "metric_id": "chronic_absenteeism_rate"},
                         DB, "High", ctx=_ctx())
    assert "ONE specific subgroup" in _err(out)
    assert "fetch_slot" not in calls


def test_subgroup_slice_sets_the_slice_not_a_slot(patch_marts):
    patch_marts(slot={"ok": True})
    ctx = _ctx()
    chat._run_tool("set_workspace_slot",
                   {"slot": "subgroup_slice", "metric_id": "chronic_absenteeism_rate",
                    "student_group_id": "el"},
                   DB, "High", ctx=ctx)
    assert ctx.spec.subgroup_slice.student_group_id == "el"
    assert "subgroup_slice" in ctx.payloads
    assert [s.student_group_id for s in ctx.spec.slots] == ["all", "all", "all"]


@pytest.mark.parametrize("slot,expected_key", [("1", "slot_1"), (3, "slot_3")])
def test_slot_number_string_is_coerced(patch_marts, slot, expected_key):
    patch_marts(slot={"ok": True})
    ctx = _ctx()
    chat._run_tool("set_workspace_slot",
                   {"slot": slot, "metric_id": "chronic_absenteeism_rate"}, DB, "High", ctx=ctx)
    assert expected_key in ctx.payloads


def test_bad_slot_value_is_a_corrective_error(patch_marts, calls):
    patch_marts(slot={"ok": True})
    out = chat._run_tool("set_workspace_slot", {"slot": 4, "metric_id": "m"}, DB, "High", ctx=_ctx())
    assert "slot must be 1, 2, 3, or 'subgroup_slice'" in _err(out)
    assert "fetch_slot" not in calls


def test_failed_slot_fetch_does_not_mutate_ctx(patch_marts):
    """A validation error from marts (unknown metric, wrong level...) reaches the model so it
    can correct — and leaves NO trace on ctx: the UI never applies an attempted slot."""
    patch_marts(slot={"error": "'martian_rate' is not a chartable metric"})
    ctx = _ctx()
    out = chat._run_tool("set_workspace_slot", {"slot": 1, "metric_id": "martian_rate"},
                         DB, "High", ctx=ctx)
    assert "not a chartable metric" in _err(out)
    assert not ctx.mutated


# ---- spotlight_plan_items ---------------------------------------------------- #
def _plan_with_goals() -> dict:
    return {"has_plan": True, "plan_status": "on_file", "plan_year": "2024-25",
            "goals": [{"goal_index": 0, "goal_number": "1", "goal_type": "attendance",
                       "statement": "Improve attendance",
                       "actions": [{"action_index": 0, "strategy_text": "Home visits"}]}]}


def test_spotlight_requires_a_plan_on_file(patch_marts):
    """No SPSA extracted → nothing to pin, and the error repeats the honesty vocabulary
    (UNKNOWN, not absent) so the model doesn't tell the user the school has no plan."""
    patch_marts(plan={"has_plan": False, "plan_status": "not_on_file", "plan_year": None, "goals": []})
    out = chat._run_tool("spotlight_plan_items", {"items": [{"goal_index": 0, "reason": "r"}]},
                         DB, "High", ctx=_ctx())
    assert "UNKNOWN, not absent" in _err(out)


def test_spotlight_happy_path_stamps_the_plan_year_into_the_spec(patch_marts):
    """The server stamps plan_year so a session restore against a NEWER extraction drops the
    stale spotlight silently (design § Plan spotlight)."""
    patch_marts(plan=_plan_with_goals())
    ctx = _ctx()
    out = chat._run_tool("spotlight_plan_items",
                         {"items": [{"goal_index": 0, "reason": "matches the attendance slot"}]},
                         DB, "High", ctx=ctx)
    assert out["items"][0]["statement"] == "Improve attendance"  # rendered from the plan rows
    assert ctx.spec.plan_spotlight.plan_year == "2024-25"
    assert ctx.spotlight is out
    assert ctx.mutated


def test_spotlight_with_only_bad_refs_errors_and_does_not_mutate(patch_marts):
    patch_marts(plan=_plan_with_goals())
    ctx = _ctx()
    out = chat._run_tool("spotlight_plan_items", {"items": [{"goal_index": 9, "reason": "r"}]},
                         DB, "High", ctx=ctx)
    assert "out-of-range" in _err(out)
    assert not ctx.mutated


def test_spotlight_empty_items_is_an_error(patch_marts):
    patch_marts(plan=_plan_with_goals())
    out = chat._run_tool("spotlight_plan_items", {"items": []}, DB, "High", ctx=_ctx())
    assert "at least one" in _err(out)


# ---- set_school --------------------------------------------------------------- #
def test_set_school_switches_ctx_and_returns_the_default_workspace(patch_marts, calls):
    """set_school = spawn/activate a session client-side: ctx re-points at the new school,
    the spec resets to the defaults, and the payloads carry the three default slots. The
    plan is NOT inlined (include_plan=False) — the tool result stays small."""
    ws = {"school_id": "NEW", "spec": {}, "slots": [{"a": 1}, {"b": 2}, {"c": 3}],
          "subgroup_slice": None, "spotlight": None}
    patch_marts(resolve=_school(school_id="NEW", name="Jordan High"), workspace=ws)
    ctx = _ctx("OLD")
    out = chat._run_tool("set_school", {"school_name": "Jordan"}, DB, "High", ctx=ctx)
    assert ctx.school_id == "NEW"
    assert ctx.school["school_name"] == "Jordan High"
    assert calls["fetch_workspace"]["args"][0] == "NEW"
    assert calls["fetch_workspace"]["kwargs"] == {"include_plan": False}
    assert ctx.payloads == {"slot_1": {"a": 1}, "slot_2": {"b": 2}, "slot_3": {"c": 3}}
    assert ctx.spec.model_dump() == chat.DEFAULT_WORKSPACE_SPEC.model_dump()
    assert out["school"]["school_name"] == "Jordan High"


def test_set_school_resets_a_previous_spotlight(patch_marts):
    """A pin belongs to the school it was made for — switching schools clears it."""
    ws = {"school_id": "NEW", "spec": {}, "slots": [{}, {}, {}],
          "subgroup_slice": None, "spotlight": None}
    patch_marts(resolve=_school(school_id="NEW"), workspace=ws)
    ctx = _ctx("OLD")
    ctx.spotlight = {"items": [{"goal_index": 0}]}
    chat._run_tool("set_school", {"school_name": "Jordan"}, DB, "High", ctx=ctx)
    assert ctx.spotlight is None
    assert ctx.spec.plan_spotlight is None


def test_set_school_unresolved_name_errors_and_keeps_the_old_school(patch_marts):
    patch_marts(resolve=None)
    ctx = _ctx("OLD")
    out = chat._run_tool("set_school", {"school_name": "Nowhere"}, DB, "High", ctx=ctx)
    assert "no High school found matching 'Nowhere'" in _err(out)
    assert ctx.school_id == "OLD"
    assert not ctx.mutated


# ---- rename_session ------------------------------------------------------------ #
def test_rename_session_records_the_title_truncated(patch_marts):
    """Session metadata only — no school guard, no DB; the client applies it to the rail."""
    patch_marts()
    ctx = chat.ToolCtx()  # deliberately schoolless — must still work
    out = chat._run_tool("rename_session", {"title": "  " + "T" * 100}, DB, "High", ctx=ctx)
    assert out["ok"] is True
    assert len(out["title"]) == 60
    assert ctx.session_title == out["title"]
    assert ctx.mutated


def test_rename_session_empty_title_is_an_error(patch_marts):
    patch_marts()
    ctx = chat.ToolCtx()
    out = chat._run_tool("rename_session", {"title": "   "}, DB, "High", ctx=ctx)
    assert "title is required" in _err(out)
    assert not ctx.mutated


# --------------------------------------------------------------------------- #
# level scoping — every tool must honor the header-selected level
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tool", [
    "find_similar_schools", "compare_to_peers", "query_school_plan", "query_subgroup_metrics",
])
def test_school_resolution_is_level_scoped(patch_marts, calls, tool):
    """The UI header's level scopes resolution server-side; a Middle-level session must never
    resolve a High school."""
    patch_marts(resolve=_school(), like={}, bench={"target_value": 1}, plan={"has_plan": True},
                subgroup={})
    chat._run_tool(tool, {"school_name": "Hoover"}, DB, "Middle")
    assert calls["_resolve_school"] == {"name": "Hoover", "level": "Middle"}
