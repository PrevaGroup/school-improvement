"""`evals.ingest_traces` — GCS JSONL -> `trace` rows, idempotently and unstoppably.

Properties under test:

  1. **parse_trace maps the emitted envelope onto the table row** — including lifting the
     verbatim question from `turn_start` (kept indefinitely, §8.3) and defaulting the
     tenancy/source fields the ingest must never leave null.
  2. **The emission side and the store side agree.** A trace built by the REAL TraceRecorder
     (app/traces.py) must parse — the JSONL contract has producers on both sides of a module
     boundary and no shared code, so this cross-check is the only thing keeping them honest.
     (evals may import app.traces in a TEST — tests are tooling, exempt from the boundary rule
     like migrations; the runtime modules still never import each other.)
  3. **One corrupt object cannot stall the pipeline** — malformed input is counted + skipped.
  4. **Idempotency is structural**: the INSERT carries ON CONFLICT (trace_id) DO NOTHING, so
     re-scanning a window can only add, never duplicate or error.

No GCS, no DB: fsspec.filesystem is faked at the exact seam ingest() reads through, and the
SQL layer is a recorder.
"""
from __future__ import annotations

import json

import pytest

from evals import ingest_traces
from evals.ingest_traces import _INSERT, ingest, parse_trace


def _envelope(**over) -> dict:
    env = {
        "trace_id": "0198f7a0-aaaa-7bbb-8ccc-dddddddddddd",
        "session_id": "sess-1",
        "ts": "2026-07-16T22:00:00+00:00",
        "latency_ms": 1234,
        "status": "ok",
        "tenant_id": "public",
        "principal_hash": "ab" * 32,
        "source": "prod",
        "ui": {"level": "High"},
        "gen_ai.provider.name": "anthropic",
        "gen_ai.request.model": "claude-haiku-4-5",
        "versions": {"git_sha": "abc123", "prompt_hash": "p" * 64, "tool_catalog_hash": "t" * 64},
        "totals": {"input_tokens": 300, "output_tokens": 100, "cost_usd_est": 0.001,
                   "iterations": 2},
        "gcs_uri": "gs://tb/traces/v1/dt=2026-07-16/x.jsonl",
    }
    env.update(over)
    return env


def _body(env: dict, *events: dict) -> str:
    return "\n".join(json.dumps(x) for x in [env, *events]) + "\n"


# --------------------------------------------------------------------------- #
# parse_trace — the envelope -> row mapping
# --------------------------------------------------------------------------- #
def test_parse_maps_envelope_and_lifts_the_question():
    body = _body(_envelope(),
                 {"type": "turn_start", "question": "how is Wilson doing?", "seq": 0},
                 {"type": "turn_end", "reply": "fine", "seq": 1})
    row = parse_trace(body, "gs://tb/x.jsonl")
    assert row["trace_id"] == "0198f7a0-aaaa-7bbb-8ccc-dddddddddddd"
    assert row["question"] == "how is Wilson doing?"     # verbatim — never shrunk (§8.3)
    assert row["status"] == "ok"
    assert row["provider"] == "anthropic"
    assert row["model"] == "claude-haiku-4-5"
    assert json.loads(row["ui"]) == {"level": "High"}    # JSONB fields travel as JSON strings
    assert json.loads(row["totals"])["iterations"] == 2
    assert row["gcs_uri"] == "gs://tb/traces/v1/dt=2026-07-16/x.jsonl"


def test_parse_defaults_the_fields_ingest_must_never_null():
    """tenant_id/source have NOT NULL columns — an old emitter version can't break ingest."""
    env = _envelope(gcs_uri=None)      # no self-reported uri -> fall back to the object path
    del env["tenant_id"], env["session_id"]
    env.pop("source")
    row = parse_trace(_body(env), "gs://tb/y.jsonl")
    assert row["tenant_id"] == "public"
    assert row["source"] == "prod"
    assert row["session_id"] is None
    assert row["question"] is None                        # no turn_start -> null, not a crash
    assert row["gcs_uri"] == "gs://tb/y.jsonl"            # falls back to the object's own path


def test_parse_rejects_a_body_that_does_not_start_with_an_envelope():
    with pytest.raises(ValueError):
        parse_trace(_body({"type": "turn_start", "trace_id": "x", "question": "?"}), "gs://z")
    with pytest.raises(Exception):
        parse_trace("not json at all", "gs://z")


def test_the_real_recorder_and_the_ingest_parse_agree():
    """The cross-module JSONL contract, checked end-to-end: emit with the real TraceRecorder,
    parse with the real parse_trace. If either side drifts, this is the test that knows."""
    from app.traces import TraceRecorder

    r = TraceRecorder(provider="anthropic", model="claude-haiku-4-5",
                      principal_sub="sub-1", ui={"level": "Middle"},
                      versions={"prompt_hash": "p" * 64, "tool_catalog_hash": "t" * 64},
                      session_id="sess-9")
    r.turn_start(question="um, what the heck is 2+2", prior_messages=0, system_hash="s" * 64)
    r.model_call(iteration=0, stop="end",
                 usage={"input_tokens": 10, "output_tokens": 5,
                        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                 latency_ms=100, content_digest="d" * 64)
    r.turn_end(reply="4", status="ok")

    body = "\n".join(json.dumps(line, default=str) for line in [r.envelope(), *r._events])
    row = parse_trace(body, "gs://tb/real.jsonl")
    assert row["trace_id"] == r.trace_id
    assert row["question"] == "um, what the heck is 2+2"  # the mess is signal — verbatim
    assert row["session_id"] == "sess-9"
    assert row["status"] == "ok"
    assert json.loads(row["totals"])["input_tokens"] == 10
    assert json.loads(row["versions"])["tool_catalog_hash"] == "t" * 64


# --------------------------------------------------------------------------- #
# ingest — listing, skip-and-log, and the write
# --------------------------------------------------------------------------- #
class _FakeFS:
    """fsspec.filesystem('gs') faked at the two calls ingest uses: glob + open."""

    def __init__(self, objects: dict[str, str]):
        self._objects = objects                            # path -> body

    def glob(self, pattern):
        prefix = pattern.split("*")[0].removeprefix("gs://")
        return [p for p in self._objects if p.startswith(prefix)]

    def open(self, path, mode):
        import io
        return io.StringIO(self._objects[path])


class _FakeConn:
    def __init__(self, log):
        self._log = log

    def execute(self, sql, row):
        self._log.append((sql, row))
        return type("R", (), {"rowcount": 1})()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake_infra(monkeypatch):
    """Wire a fake GCS listing + a recording SQL connection into ingest()."""
    state = {"objects": {}, "executed": []}

    import fsspec
    monkeypatch.setattr(fsspec, "filesystem", lambda proto: _FakeFS(state["objects"]))

    class _Eng:
        def begin(self):
            return _FakeConn(state["executed"])

    import evals._db as db
    monkeypatch.setattr(db, "_engine", lambda: _Eng())
    return state


def test_ingest_upserts_every_parseable_object_and_skips_the_corrupt_one(fake_infra):
    good1 = _body(_envelope(trace_id="t-1"), {"type": "turn_start", "question": "q1"})
    good2 = _body(_envelope(trace_id="t-2"), {"type": "turn_start", "question": "q2"})
    fake_infra["objects"] = {
        "tb/traces/v1/dt=2026-07-16/t-1.jsonl": good1,
        "tb/traces/v1/dt=2026-07-16/t-2.jsonl": good2,
        "tb/traces/v1/dt=2026-07-16/corrupt.jsonl": "{{{ not json",
    }
    counts = ingest("tb", one_date="2026-07-16")
    assert counts == {"objects": 3, "inserted": 2, "skipped_malformed": 1}
    inserted = {row["trace_id"] for _sql, row in fake_infra["executed"]}
    assert inserted == {"t-1", "t-2"}


def test_ingest_is_idempotent_by_construction():
    """The guarantee is structural — ON CONFLICT (trace_id) DO NOTHING in the one INSERT —
    so a re-scanned window (the default --days 3 overlap) can never duplicate or error."""
    sql = str(_INSERT)
    assert "ON CONFLICT (trace_id) DO NOTHING" in sql


def test_dry_run_writes_nothing(fake_infra):
    fake_infra["objects"] = {
        "tb/traces/v1/dt=2026-07-16/t-1.jsonl":
            _body(_envelope(trace_id="t-1"), {"type": "turn_start", "question": "q"}),
    }
    counts = ingest("tb", one_date="2026-07-16", dry_run=True)
    assert counts["inserted"] == 1                        # what WOULD be attempted
    assert fake_infra["executed"] == []                   # and nothing was


def test_default_window_scans_three_day_partitions():
    """No watermark by design: late fire-and-forget flushes land inside their dt= partition,
    and the 3-day re-scan + idempotent insert absorbs them."""
    pats = ingest_traces._partitions("tb", days=3, one_date=None)
    assert len(pats) == 3
    assert all(p.startswith("gs://tb/traces/v1/dt=") and p.endswith("/*.jsonl") for p in pats)
