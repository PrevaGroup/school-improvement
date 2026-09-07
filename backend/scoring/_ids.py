"""Time-ordered id minting for scoring-owned rows.

A deliberate near-copy of `evals/_ids.py`, for the same reason it is a near-copy of
`app.traces.uuid7`: that one is serving-owned and this module may not import it. Time-ordered ids
keep score_event and artifact rows sortable by creation without a second index.
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
