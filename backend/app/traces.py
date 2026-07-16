"""Trace emission for /api/chat — phase 1 of the eval trace system.

One JSONL object per turn to `gs://<TRACES_BUCKET>/traces/v1/dt=YYYY-MM-DD/<trace_id>.jsonl`,
plus a one-line structured ops log. Design: docs/design/eval-trace-system.md (§1-2, §8).

Three rules, all decided (§8):

- **This is a logging write, not a durable one.** `flush()` never raises and nothing retries;
  a lost trace logs a warning and nearly doesn't matter. Chat must work when tracing is down,
  and tracing must never add latency — the caller flushes in a FastAPI BackgroundTask after
  the response is sent (inline only on error paths, where latency is already lost).
- **Serving owns no tables.** Traces land in GCS; the `evals` producer module (phase 2)
  ingests them in batch. Nothing here touches Postgres.
- **Vendor-agnostic.** This module speaks only the neutral vocabulary — OTel GenAI field
  names, normalized `stop` values (`tool_use · end · max_tokens · refusal`), normalized token
  kinds. Provider wire formats (e.g. Anthropic's `stop_reason`) must be mapped by the caller
  *before* anything reaches the recorder; today that mapping lives in chat.py, and it moves
  into `AnthropicRunner` when the AgentRunner seam lands (phase 5).

Identity: traces carry `principal_hash` (salted SHA-256 of the verified `sub`), never email —
the join to a person exists only via the salt, held like other secrets. Unset TRACES_BUCKET
disables emission entirely (the dev default); the ops log line is emitted regardless.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from .config import settings
from .usage import estimate_cost_usd

log = logging.getLogger(__name__)

# The four token kinds every provider's usage normalizes into (matches estimate_cost_usd's
# signature, so the envelope's cost is denominated in the same function as the spend caps).
TOKEN_KINDS = ("input_tokens", "output_tokens",
               "cache_read_input_tokens", "cache_creation_input_tokens")


def uuid7() -> str:
    """Time-ordered UUIDv7 (RFC 9562). Stdlib grows uuid.uuid7() in 3.14; CI runs 3.13."""
    ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFF_FFFF_FFFF_FFFF
    return str(uuid.UUID(int=(ms << 80) | (0x7 << 76) | (rand_a << 64) | (0x2 << 62) | rand_b))


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _principal_hash(sub: str) -> str | None:
    """Salted hash of the verified `sub`. None (never a raise, never a raw sub) when the salt
    is unavailable — a trace without identity beats no trace, and beats leaking the sub."""
    try:
        return sha256_hex(settings.trace_salt_value + sub)
    except Exception:
        log.warning("trace salt unavailable — emitting trace without principal_hash")
        return None


def _git_sha() -> str | None:
    # GIT_SHA is stamped by the deploy; K_REVISION (set by Cloud Run) at least pins the
    # revision when it isn't. Neither exists in dev — None is honest there.
    return settings.git_sha or os.environ.get("K_REVISION")


class TraceRecorder:
    """Buffers one turn's events in memory; `flush()` writes the JSONL object + ops log line.

    Event stream (schema v1, §2): `turn_start` → `model_call`/`tool_call`... → `turn_end`,
    each `{trace_id, span_id, parent_span_id, seq, ts, type, ...}` nested under the turn's
    root span. The `type` vocabulary is open — new agent-loop capabilities become new span
    types, not schema breaks.
    """

    def __init__(self, *, provider: str, model: str, principal_sub: str,
                 ui: dict, versions: dict, session_id: str | None = None,
                 source: str = "prod", tenant_id: str = "public") -> None:
        self.trace_id = uuid7()
        self.ts = datetime.now(timezone.utc)
        self._t0 = time.perf_counter()
        self._root_span = os.urandom(8).hex()
        self._events: list[dict] = []
        self._principal_sub = principal_sub          # hashed at flush, never serialized
        self.session_id = session_id
        self.source = source
        self.tenant_id = tenant_id
        self.ui = ui
        self.provider = provider
        self.model = model
        self.versions = versions
        self.status = "ok"                           # ok · refusal · error · max_iters
        self.latency_ms: int | None = None           # frozen at turn_end (or flush, on error)
        self.iterations = 0
        self.tools_used: list[str] = []
        self.totals: dict[str, int] = {k: 0 for k in TOKEN_KINDS}

    # ------------------------------------------------------------------ events
    def _event(self, type_: str, payload: dict) -> None:
        self._events.append({
            "trace_id": self.trace_id,
            "span_id": os.urandom(8).hex(),
            "parent_span_id": None if type_ == "turn_start" else self._root_span,
            "seq": len(self._events),
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": type_,
            **payload,
        })
        if type_ == "turn_start":                    # the turn IS the root span
            self._events[-1]["span_id"] = self._root_span

    def turn_start(self, *, question: str, prior_messages: int, system_hash: str) -> None:
        self._event("turn_start", {"question": question, "prior_messages": prior_messages,
                                   "system_prompt_hash": system_hash})

    def model_call(self, *, iteration: int, stop: str, usage: dict,
                   latency_ms: int, content_digest: str) -> None:
        """`stop` and `usage` arrive ALREADY NORMALIZED — see the module docstring."""
        self.iterations += 1
        for k in TOKEN_KINDS:
            self.totals[k] += usage.get(k) or 0
        self._event("model_call", {
            "iteration": iteration,
            "gen_ai.provider.name": self.provider,
            "gen_ai.request.model": self.model,
            "stop": stop,
            "usage": {k: usage.get(k) or 0 for k in TOKEN_KINDS},
            "latency_ms": latency_ms,
            "content_digest": content_digest,
        })

    def tool_call(self, *, name: str, input: dict, output: dict,
                  latency_ms: int, error: str | None = None) -> None:
        self.tools_used.append(name)
        self._event("tool_call", {"name": name, "input": input, "output": output,
                                  "error": error, "latency_ms": latency_ms})

    def turn_end(self, *, reply: str, status: str = "ok") -> None:
        self.status = status
        self.latency_ms = int((time.perf_counter() - self._t0) * 1000)
        self._event("turn_end", {"reply": reply, "tools_used": sorted(set(self.tools_used)),
                                 "totals": dict(self.totals)})

    # ---------------------------------------------------------------- envelope
    def _gcs_uri(self) -> str | None:
        if not settings.traces_bucket:
            return None
        return (f"gs://{settings.traces_bucket}/traces/v1/"
                f"dt={self.ts.date().isoformat()}/{self.trace_id}.jsonl")

    def envelope(self) -> dict:
        """The first JSONL line — and, verbatim, the `trace` table row phase 2 ingests."""
        if self.latency_ms is None:                  # error path skipped turn_end
            self.latency_ms = int((time.perf_counter() - self._t0) * 1000)
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "ts": self.ts.isoformat(),
            "latency_ms": self.latency_ms,
            "status": self.status,
            "tenant_id": self.tenant_id,
            "principal_hash": _principal_hash(self._principal_sub),
            "source": self.source,
            "ui": self.ui,
            "gen_ai.provider.name": self.provider,
            "gen_ai.request.model": self.model,
            "versions": {"git_sha": _git_sha(), **self.versions},
            "totals": {
                **self.totals,
                "cost_usd_est": estimate_cost_usd(self.model, **self.totals),
                "iterations": self.iterations,
            },
            "gcs_uri": self._gcs_uri(),
        }

    # ------------------------------------------------------------------- flush
    def flush(self) -> None:
        """Write ops log line + GCS object. NEVER raises — see the module docstring."""
        try:
            env = self.envelope()
            # The ops line: enough to debug a turn from Cloud Logging without a DB round-trip.
            log.info("chat_trace %s", json.dumps({
                "trace_id": env["trace_id"], "status": env["status"],
                "latency_ms": env["latency_ms"], "totals": env["totals"],
                "tools_used": sorted(set(self.tools_used)),
                "model": self.model, "source": self.source,
            }, default=str))
            if not env["gcs_uri"]:
                return                               # tracing disabled (no bucket configured)
            body = "\n".join(json.dumps(line, default=str)
                             for line in [env, *self._events]) + "\n"
            import fsspec                            # deferred: only the flush needs it

            with fsspec.open(env["gcs_uri"], "w") as f:
                f.write(body)
        except Exception:
            log.warning("trace flush failed — trace %s dropped", self.trace_id, exc_info=True)
