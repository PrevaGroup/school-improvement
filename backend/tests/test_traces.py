"""The trace emission layer (app/traces.py + chat.py wiring) — eval-trace-system.md phase 1.

Properties under test, in order of how expensive they'd be to lose:

  1. **Tracing can never break chat.** flush() swallows everything; an unset bucket disables
     emission entirely; a missing salt degrades to a null principal_hash. The hot path gains
     one BackgroundTask on success and one inline (still never-raising) flush on error.
  2. **The trace speaks the neutral vocabulary.** Normalized `stop` values, OTel GenAI field
     names, no raw Anthropic `stop_reason` in any event — the vendor-agnostic invariant (§8.4)
     starts here, before the AgentRunner seam exists.
  3. **Identity is hashed, never raw.** The verified `sub` must not appear anywhere in the
     serialized trace; the envelope carries a salted hash or null.
  4. **The envelope is the future `trace` table row** — totals, cost (denominated in
     estimate_cost_usd, same as the spend caps), status, versions.

No GCS, no DB, no model calls: fsspec is patched at the exact seam flush() writes through,
anthropic is a fake module, and the mart layer is patched as in test_chat_tools.py.
"""
from __future__ import annotations

import json
import logging
import sys
import types
import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException

from app import chat, traces
from app.traces import TraceRecorder, sha256_hex, uuid7
from app.usage import estimate_cost_usd


def _recorder(**over) -> TraceRecorder:
    kw = dict(provider="anthropic", model="claude-haiku-4-5", principal_sub="user-sub-1",
              ui={"level": "High"}, versions={"prompt_hash": "p" * 64, "tool_catalog_hash": "t" * 64})
    kw.update(over)
    return TraceRecorder(**kw)


# --------------------------------------------------------------------------- #
# uuid7 — time-ordered ids are what makes the GCS listing and the trace table scannable
# --------------------------------------------------------------------------- #
def test_uuid7_is_version_7_and_time_ordered():
    import time
    a = uuid7()
    time.sleep(0.005)          # cross a millisecond boundary — intra-ms order isn't promised
    b = uuid7()
    assert uuid.UUID(a).version == 7
    assert a < b               # the 48-bit ms prefix makes lexicographic order = time order


# --------------------------------------------------------------------------- #
# the recorder — event stream shape + envelope
# --------------------------------------------------------------------------- #
def _run_one_turn(r: TraceRecorder) -> None:
    r.turn_start(question="how is Wilson doing?", prior_messages=2, system_hash="s" * 64)
    r.model_call(iteration=0, stop="tool_use",
                 usage={"input_tokens": 100, "output_tokens": 10,
                        "cache_read_input_tokens": 50, "cache_creation_input_tokens": 5},
                 latency_ms=800, content_digest="d" * 64)
    r.tool_call(name="compare_to_peers", input={"school_name": "Wilson"},
                output={"target_value": 25.0}, latency_ms=40)
    r.model_call(iteration=1, stop="end",
                 usage={"input_tokens": 200, "output_tokens": 90,
                        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                 latency_ms=900, content_digest="e" * 64)
    r.turn_end(reply="Wilson is doing fine.", status="ok")


def test_event_stream_shape():
    """turn_start is the root span; every other event nests under it; seq is total order."""
    r = _recorder()
    _run_one_turn(r)
    ev = r._events
    assert [e["type"] for e in ev] == ["turn_start", "model_call", "tool_call",
                                       "model_call", "turn_end"]
    assert [e["seq"] for e in ev] == [0, 1, 2, 3, 4]
    root = ev[0]["span_id"]
    assert ev[0]["parent_span_id"] is None
    assert all(e["parent_span_id"] == root for e in ev[1:])
    assert all(e["trace_id"] == r.trace_id for e in ev)


def test_envelope_totals_cost_and_versions():
    """The envelope is verbatim the future `trace` table row (phase 2 ingests it as-is)."""
    r = _recorder(session_id="sess-9")
    _run_one_turn(r)
    env = r.envelope()
    assert env["totals"]["input_tokens"] == 300
    assert env["totals"]["output_tokens"] == 100
    assert env["totals"]["cache_read_input_tokens"] == 50
    assert env["totals"]["iterations"] == 2
    # Cost is denominated in the SAME function as the spend caps — one pricing truth.
    assert env["totals"]["cost_usd_est"] == pytest.approx(
        estimate_cost_usd("claude-haiku-4-5", 300, 100, 50, 5))
    assert env["status"] == "ok"
    assert env["session_id"] == "sess-9"
    assert env["tenant_id"] == "public"      # present from day one (§6)
    assert env["source"] == "prod"
    assert env["gen_ai.provider.name"] == "anthropic"
    assert env["gen_ai.request.model"] == "claude-haiku-4-5"
    assert env["versions"]["prompt_hash"] == "p" * 64
    assert env["versions"]["tool_catalog_hash"] == "t" * 64
    assert "git_sha" in env["versions"]      # None in dev is honest; the KEY must exist
    assert env["latency_ms"] is not None


def test_model_call_events_carry_normalized_fields_only():
    """The vendor-agnostic invariant, pinned at the schema: OTel names + normalized stop,
    and no Anthropic wire-format key anywhere in the event."""
    r = _recorder()
    _run_one_turn(r)
    mc = next(e for e in r._events if e["type"] == "model_call")
    assert mc["gen_ai.provider.name"] == "anthropic"
    assert mc["stop"] == "tool_use"
    assert "stop_reason" not in json.dumps(r._events)   # the Anthropic name must not leak


# --------------------------------------------------------------------------- #
# flush — the logging write: best-effort, never-raising, privacy-preserving
# --------------------------------------------------------------------------- #
@pytest.fixture
def gcs_spy(monkeypatch):
    """Patch fsspec.open at the exact seam flush() writes through; capture path + body."""
    import fsspec
    written = {}

    class _F:
        def __init__(self, path):
            written["path"] = path
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def write(self, body):
            written["body"] = body

    monkeypatch.setattr(fsspec, "open", lambda path, mode: _F(path))
    return written


def test_flush_writes_one_jsonl_object_per_line_to_dated_path(monkeypatch, gcs_spy):
    monkeypatch.setattr(traces.settings, "traces_bucket", "tb")
    monkeypatch.setattr(traces.settings, "trace_salt", "pepper")
    r = _recorder()
    _run_one_turn(r)
    r.flush()
    assert gcs_spy["path"] == f"gs://tb/traces/v1/dt={r.ts.date().isoformat()}/{r.trace_id}.jsonl"
    lines = [json.loads(x) for x in gcs_spy["body"].strip().splitlines()]
    assert lines[0]["trace_id"] == r.trace_id            # first line: the envelope
    assert lines[0]["gcs_uri"] == gcs_spy["path"]
    assert [x["type"] for x in lines[1:]] == ["turn_start", "model_call", "tool_call",
                                              "model_call", "turn_end"]


def test_flushed_trace_carries_salted_hash_and_never_the_raw_sub(monkeypatch, gcs_spy):
    """Identity rule (§6): principal_hash = sha256(salt + sub); the raw sub appears NOWHERE."""
    monkeypatch.setattr(traces.settings, "traces_bucket", "tb")
    monkeypatch.setattr(traces.settings, "trace_salt", "pepper")
    r = _recorder(principal_sub="raw-sub-SECRET")
    _run_one_turn(r)
    r.flush()
    env = json.loads(gcs_spy["body"].splitlines()[0])
    assert env["principal_hash"] == sha256_hex("pepper" + "raw-sub-SECRET")
    assert "raw-sub-SECRET" not in gcs_spy["body"]


def test_missing_salt_degrades_to_null_hash_not_a_crash(monkeypatch, gcs_spy):
    """No salt available -> hash is null and the trace still lands. Dropping identity beats
    dropping the trace, and both beat leaking the sub unhashed."""
    monkeypatch.setattr(traces.settings, "traces_bucket", "tb")
    monkeypatch.setattr(traces.settings, "trace_salt", None)
    monkeypatch.setattr(traces.settings, "gcp_project", None)   # Secret Manager unreachable
    r = _recorder()
    _run_one_turn(r)
    r.flush()
    assert json.loads(gcs_spy["body"].splitlines()[0])["principal_hash"] is None


def test_flush_swallows_gcs_failure_and_logs_the_drop(monkeypatch, caplog):
    """§8.1 verbatim: a failed trace write logs a warning and NEVER raises. No retries."""
    import fsspec
    monkeypatch.setattr(traces.settings, "traces_bucket", "tb")
    monkeypatch.setattr(traces.settings, "trace_salt", "pepper")
    monkeypatch.setattr(fsspec, "open",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("gcs is down")))
    r = _recorder()
    _run_one_turn(r)
    with caplog.at_level(logging.WARNING, logger="app.traces"):
        r.flush()                                        # must not raise
    assert r.trace_id in caplog.text and "dropped" in caplog.text


def test_no_bucket_means_no_write_but_the_ops_line_still_logs(monkeypatch, caplog):
    """TRACES_BUCKET unset (dev default): GCS untouched, but the one-line structured ops log
    (trace_id, status, latency, totals, tools) still covers debugging."""
    import fsspec
    monkeypatch.setattr(traces.settings, "traces_bucket", None)
    monkeypatch.setattr(fsspec, "open",
                        lambda *a, **k: pytest.fail("must not touch GCS with no bucket"))
    r = _recorder()
    _run_one_turn(r)
    with caplog.at_level(logging.INFO, logger="app.traces"):
        r.flush()
    line = next(m for m in caplog.messages if m.startswith("chat_trace"))
    ops = json.loads(line.removeprefix("chat_trace "))
    assert ops["trace_id"] == r.trace_id
    assert ops["status"] == "ok"
    assert ops["tools_used"] == ["compare_to_peers"]


# --------------------------------------------------------------------------- #
# the Anthropic -> neutral mapping (lives in chat.py — today's de-facto adapter)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("wire,neutral", [
    ("tool_use", "tool_use"), ("end_turn", "end"), ("stop_sequence", "end"),
    ("max_tokens", "max_tokens"), ("refusal", "refusal"),
])
def test_stop_reasons_normalize_per_the_design_table(wire, neutral):
    assert chat._norm_stop(wire) == neutral


def test_unknown_stop_passes_through_raw_never_invented():
    """Open vocabulary: a stop we've never seen reaches the miner as itself, not as a guess."""
    assert chat._norm_stop("pause_turn") == "pause_turn"
    assert chat._norm_stop(None) == "unknown"


def test_tool_catalog_hash_is_computed_from_tools():
    """Computed, not hand-bumped (§2): editing any tool definition changes the hash."""
    assert chat.TOOL_CATALOG_HASH == sha256_hex(json.dumps(chat.TOOLS, sort_keys=True))


# --------------------------------------------------------------------------- #
# endpoint wiring — a full fake-Anthropic turn through chat()
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
    """Install a fake `anthropic` module whose client returns `responses` in order."""
    mod = types.ModuleType("anthropic")

    class APIStatusError(Exception):
        def __init__(self, message="boom", status_code=500):
            super().__init__(message)
            self.message, self.status_code = message, status_code

    class APIConnectionError(Exception):
        pass

    class _Messages:
        def __init__(self, seq):
            self._seq = list(seq)

        def create(self, **_kw):
            item = self._seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    class Anthropic:
        def __init__(self, api_key=None):
            self.messages = _Messages(responses)

    mod.Anthropic, mod.APIStatusError, mod.APIConnectionError = \
        Anthropic, APIStatusError, APIConnectionError
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return mod


@pytest.fixture
def spy_recorders(monkeypatch):
    """Subclass spy: capture every recorder chat() creates, and whether it flushed."""
    created = []

    class Spy(TraceRecorder):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.flushed = False
            created.append(self)

        def flush(self):
            self.flushed = True
            super().flush()

    monkeypatch.setattr(chat, "TraceRecorder", Spy)
    return created


@pytest.fixture
def quiet_endpoint(monkeypatch):
    """Neutralize the endpoint's non-trace dependencies: caps, usage, marts, API key, bucket."""
    monkeypatch.setattr(chat, "check_spend_caps", lambda db, sub: None)
    monkeypatch.setattr(chat, "record_chat_usage", lambda db, **kw: None)
    monkeypatch.setattr(chat, "_run_tool", lambda name, ti, db, lvl, ctx=None: {"peers": []})
    monkeypatch.setattr(chat.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(traces.settings, "traces_bucket", None)  # ops line only — no GCS


def _call(req_kw, background_tasks):
    req = chat.ChatRequest(**req_kw)
    return chat.chat(req, background_tasks, db=object(),
                     principal={"sub": "user-1", "email": "t@example.com"})


def test_happy_turn_flushes_in_background_after_the_response(
        monkeypatch, spy_recorders, quiet_endpoint):
    _fake_anthropic(monkeypatch, [
        _Resp("tool_use", [_Text("let me check"),
                           _ToolUse("find_similar_schools", {"school_name": "Wilson"})]),
        _Resp("end_turn", [_Text("Wilson's peers are ...")]),
    ])
    bt = BackgroundTasks()
    out = _call({"messages": [{"role": "user", "content": "who is Wilson like?"}],
                 "session_id": "sess-1"}, bt)
    assert out["reply"] == "Wilson's peers are ..."
    r = spy_recorders[0]
    assert not r.flushed                     # NOT flushed on the hot path...
    assert len(bt.tasks) == 1
    bt.tasks[0].func()                       # ...the background task does it
    assert r.flushed
    assert r.status == "ok"
    assert r.session_id == "sess-1"
    assert r.ui == {"level": "High"}
    assert [e["type"] for e in r._events] == ["turn_start", "model_call", "tool_call",
                                              "model_call", "turn_end"]
    assert r._events[1]["stop"] == "tool_use" and r._events[3]["stop"] == "end"
    assert r.totals["input_tokens"] == 200   # two model calls, summed
    assert r.versions["tool_catalog_hash"] == chat.TOOL_CATALOG_HASH


def test_model_error_flushes_inline_because_background_tasks_die_with_the_500(
        monkeypatch, spy_recorders, quiet_endpoint):
    """FastAPI drops the background queue when a handler raises — so the error path must
    flush before raising, and the trace must say `error`."""
    responses: list = []
    mod = _fake_anthropic(monkeypatch, responses)
    # Appended AFTER install so the raised error is an instance of the SAME class the
    # endpoint's `except anthropic.APIStatusError` resolves to.
    responses.append(mod.APIStatusError(message="model fell over", status_code=500))
    bt = BackgroundTasks()
    with pytest.raises(HTTPException) as e:
        _call({"messages": [{"role": "user", "content": "hi"}]}, bt)
    assert e.value.status_code == 502
    r = spy_recorders[0]
    assert r.flushed                         # inline, before the raise
    assert r.status == "error"
    assert len(bt.tasks) == 0


def test_refusal_is_its_own_status(monkeypatch, spy_recorders, quiet_endpoint):
    _fake_anthropic(monkeypatch, [_Resp("refusal", [])])
    bt = BackgroundTasks()
    out = _call({"messages": [{"role": "user", "content": "do crimes"}]}, bt)
    assert "declined" in out["reply"]
    bt.tasks[0].func()
    assert spy_recorders[0].status == "refusal"


def test_exhausting_the_tool_loop_is_max_iters_not_ok(
        monkeypatch, spy_recorders, quiet_endpoint):
    """The miner treats max_iters exits as failure candidates (§4) — they must be labeled."""
    loop_forever = [_Resp("tool_use", [_ToolUse("find_similar_schools", {"school_name": "W"})])
                    for _ in range(chat.MAX_TOOL_ITERS + 1)]
    _fake_anthropic(monkeypatch, loop_forever)
    bt = BackgroundTasks()
    _call({"messages": [{"role": "user", "content": "loop"}]}, bt)
    bt.tasks[0].func()
    r = spy_recorders[0]
    assert r.status == "max_iters"
    assert r.iterations == chat.MAX_TOOL_ITERS + 1
