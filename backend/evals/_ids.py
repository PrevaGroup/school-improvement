"""Time-ordered id minting for evals-owned rows (eval_case_id, eval_run_id).

A deliberate near-copy of `app.traces.uuid7` (which is serving-owned, so this module may not
import it — same honest-duplication call as `evals/_db.py` vs `sip/_db.py`). Time-ordered ids
keep eval_case / eval_run rows naturally sortable by creation, matching how `trace_id` behaves.
"""
from __future__ import annotations

import os
import time
import uuid


def uuid7() -> str:
    """Time-ordered UUIDv7 (RFC 9562). Stdlib grows uuid.uuid7() in 3.14; CI runs 3.13."""
    ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFF_FFFF_FFFF_FFFF
    return str(uuid.UUID(int=(ms << 80) | (0x7 << 76) | (rand_a << 64) | (0x2 << 62) | rand_b))
