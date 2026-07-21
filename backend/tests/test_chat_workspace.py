"""Endpoint-level workspace threading through `chat()` — request in, response out.

What only THIS level can see (tool-level tests can't): (1) the response's `workspace`
field carries the turn's accumulated mutations with the SAME server-built payloads the
model received as tool results — the one-round-trip contract the UI applies without a
refetch; (2) a turn with no workspace tool leaves the response shape byte-identical to
the pre-workspace API (strictly additive — the deployed frontend keeps working);
(3) the request's on-screen spec is rendered into the system prompt (the grounding for
"don't regurgitate the screen") and into the trace envelope's `ui` dict.

Fake-Anthropic pattern copied from tests/test_traces.py: `chat()` imports `anthropic`
lazily inside the endpoint, so installing a fake module via sys.modules is enough.

Run:  python -m pytest tests/test_chat_workspace.py -v
"""
import sys
import types

import pytest
from fastapi import BackgroundTasks

from app import chat, traces


# --------------------------------------------------------------------------- #
# fake Anthropic wire objects (mirrors test_traces.py)
# --------------------------------------------------------------------------- #
class _Usage:
    input_tokens = 100
    output_tokens = 10
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _ToolUse:
    type = "tool_use"

    def __init__(self, name, input):
        self.name, self.input, self.id = name, input, "tu_1"


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason, self.content, self.usage = stop_reason, content, _Usage()


def _fake_anthropic(monkeypatch, responses):
    mod = types.ModuleType("anthropic")

    class APIStatusError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    class _Messages:
        def __init__(self, seq):
            self._seq = list(seq)

        def create(self, **kw):
            _fake_anthropic.last_create = kw  # the system prompt actually sent
            return self._seq.pop(0)

    class Anthropic:
        def __init__(self, api_key=None):
            self.messages = _Messages(responses)

    mod.Anthropic, mod.APIStatusError, mod.APIConnectionError = \
        Anthropic, APIStatusError, APIConnectionError
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return mod


@pytest.fixture
def quiet(monkeypatch):
    """Neutralize the endpoint's non-workspace dependencies (caps, usage, key, GCS)."""
    monkeypatch.setattr(chat, "check_spend_caps", lambda db, sub: None)
    monkeypatch.setattr(chat, "record_chat_usage", lambda db, **kw: None)
    monkeypatch.setattr(chat.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(traces.settings, "traces_bucket", None)


def _call(req_kw: dict) -> dict:
    req = chat.ChatRequest(**req_kw)
    return chat.chat(req, BackgroundTasks(), db=object(),
                     principal={"sub": "user-1", "email": "t@example.com"})


DEFAULT_SLOTS = [{"metric_id": "chronic_absenteeism_rate"},
                 {"metric_id": "grad_rate_acgr"},
                 {"metric_id": "college_going_rate"}]


# --------------------------------------------------------------------------- #
# the one-round-trip contract
# --------------------------------------------------------------------------- #
def test_workspace_mutations_ride_the_response(monkeypatch, quiet):
    payload = {"slot_spec": {"metric_id": "suspension_rate"}, "target_value": 12.0}
    monkeypatch.setattr(chat, "fetch_slot",
                        lambda db, sid, spec, lvl=None, refs=None: payload)
    _fake_anthropic(monkeypatch, [
        _Resp("tool_use", [_ToolUse("set_workspace_slot",
                                    {"slot": 1, "metric_id": "suspension_rate"})]),
        _Resp("end_turn", [_Text("slot 1 now shows suspensions")]),
    ])
    out = _call({"messages": [{"role": "user", "content": "show suspensions"}],
                 "school_id": "S1", "workspace": {"slots": DEFAULT_SLOTS}})
    ws = out["workspace"]
    assert ws["payloads"]["slot_1"] is payload      # the exact payload the model saw
    assert ws["spec"]["slots"][0]["metric_id"] == "suspension_rate"
    assert ws["spec"]["slots"][1]["metric_id"] == "grad_rate_acgr"  # untouched slot preserved
    assert ws["school"] is None                     # set_school didn't run
    assert out["tools_used"] == ["set_workspace_slot"]


def test_response_is_unchanged_when_no_workspace_tool_runs(monkeypatch, quiet):
    """Strictly additive: without a workspace mutation the response has NO workspace key —
    the pre-workspace frontend keeps parsing exactly what it always got. (`trace_id` is the
    always-present base field, additive and ignored by older clients.)"""
    _fake_anthropic(monkeypatch, [_Resp("end_turn", [_Text("hello")])])
    out = _call({"messages": [{"role": "user", "content": "hi"}]})
    assert set(out) == {"reply", "tools_used", "trace_id"}


def test_failed_slot_attempt_leaves_no_workspace_in_the_response(monkeypatch, quiet):
    """An attempted-but-rejected slot must not reach the UI: the model sees the corrective
    error; the response carries no workspace field at all."""
    monkeypatch.setattr(chat, "fetch_slot",
                        lambda db, sid, spec, lvl=None, refs=None: {"error": "not chartable"})
    _fake_anthropic(monkeypatch, [
        _Resp("tool_use", [_ToolUse("set_workspace_slot", {"slot": 1, "metric_id": "bad"})]),
        _Resp("end_turn", [_Text("that metric isn't chartable")]),
    ])
    out = _call({"messages": [{"role": "user", "content": "chart badness"}],
                 "school_id": "S1", "workspace": {"slots": DEFAULT_SLOTS}})
    assert "workspace" not in out


# --------------------------------------------------------------------------- #
# screen-state grounding
# --------------------------------------------------------------------------- #
def test_on_screen_spec_is_rendered_into_the_system_prompt(monkeypatch, quiet):
    _fake_anthropic(monkeypatch, [_Resp("end_turn", [_Text("ok")])])
    _call({"messages": [{"role": "user", "content": "hi"}],
           "school_id": "S1",
           "workspace": {"slots": [{"metric_id": "chronic_absenteeism_rate"},
                                   {"metric_id": "grad_rate_acgr", "school_year": "2022-23"},
                                   {"metric_id": "college_going_rate"}]}})
    system = _fake_anthropic.last_create["system"]
    assert "Slot 2: grad_rate_acgr · 2022-23 · all" in system
    assert "Subgroup box 1: (empty)" in system


def test_no_workspace_request_keeps_the_prompt_and_trace_ui_unchanged(monkeypatch, quiet):
    """Back-compat pin: a workspace-less request produces the pre-workspace system prompt
    (no screen-state section) and the pre-workspace trace ui dict."""
    seen = {}

    class Spy(traces.TraceRecorder):
        def __init__(self, **kw):
            seen.update(kw)
            super().__init__(**kw)

    monkeypatch.setattr(chat, "TraceRecorder", Spy)
    _fake_anthropic(monkeypatch, [_Resp("end_turn", [_Text("ok")])])
    _call({"messages": [{"role": "user", "content": "hi"}]})
    assert "THE WORKSPACE CURRENTLY SHOWS" not in _fake_anthropic.last_create["system"]
    assert seen["ui"] == {"level": "High"}


def test_trace_ui_carries_the_workspace_spec_when_sent(monkeypatch, quiet):
    seen = {}

    class Spy(traces.TraceRecorder):
        def __init__(self, **kw):
            seen.update(kw)
            super().__init__(**kw)

    monkeypatch.setattr(chat, "TraceRecorder", Spy)
    _fake_anthropic(monkeypatch, [_Resp("end_turn", [_Text("ok")])])
    _call({"messages": [{"role": "user", "content": "hi"}],
           "workspace": {"slots": DEFAULT_SLOTS}})
    assert seen["ui"]["level"] == "High"
    assert seen["ui"]["workspace"]["slots"][0]["metric_id"] == "chronic_absenteeism_rate"


# --------------------------------------------------------------------------- #
# set_school mid-turn re-points the following slot calls
# --------------------------------------------------------------------------- #
def test_set_school_repoints_later_slot_calls_in_the_same_turn(monkeypatch, quiet):
    """"Let's look at Jordan — show its suspensions": the slot call AFTER set_school must
    target the NEW school, not the one the request came in with."""
    slot_calls = []
    monkeypatch.setattr(chat, "fetch_slot",
                        lambda db, sid, spec, lvl=None, refs=None:
                        slot_calls.append(sid) or {"slot_spec": spec.model_dump()})
    monkeypatch.setattr(chat, "fetch_workspace",
                        lambda db, sid, spec, include_plan=True:
                        {"school_id": sid, "spec": spec.model_dump(),
                         "slots": [{}, {}, {}], "subgroup_slots": [None, None, None], "spotlight": None})
    monkeypatch.setattr(chat, "_resolve_school",
                        lambda db, name, lvl: {"school_id": "JORDAN", "school_name": "Jordan High",
                                               "district_id": "0622500"})
    _fake_anthropic(monkeypatch, [
        _Resp("tool_use", [_ToolUse("set_school", {"school_name": "Jordan"})]),
        _Resp("tool_use", [_ToolUse("set_workspace_slot",
                                    {"slot": 1, "metric_id": "suspension_rate"})]),
        _Resp("end_turn", [_Text("done")]),
    ])
    out = _call({"messages": [{"role": "user", "content": "look at Jordan, show suspensions"}],
                 "school_id": "OLD", "workspace": {"slots": DEFAULT_SLOTS}})
    assert slot_calls == ["JORDAN"]
    assert out["workspace"]["school"]["school_name"] == "Jordan High"
    assert out["workspace"]["payloads"]["slot_1"]["slot_spec"]["metric_id"] == "suspension_rate"
