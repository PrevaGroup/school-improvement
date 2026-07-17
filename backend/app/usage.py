"""The Claude spend cap for /api/chat — core-owned, the last gate blocker (§3.4).

Why this exists: `--no-allow-unauthenticated` is currently doing two jobs — gating access
AND capping Anthropic spend, because /api/chat pays per token and had no app-level limit.
The allowlist replaced the first job (WHO gets in); this replaces the second (HOW MUCH each
of them, and all of them together, can spend per day). Only after both exist can the IAM
gate come off.

Design (agreed 2026-07-17):
- Raw token counts land in `usage_chat_daily` at (principal_sub, UTC day, model) grain;
  dollars are DERIVED here from MODEL_PRICES at read time, never stored.
- Two caps, both required: per-user/day and global/day. The per-user cap bounds one runaway
  tester; the global cap bounds (cap x number of allowlisted users), which is the real
  exposure.
- FAILS CLOSED. Counter store unreachable -> chat is refused. Chat is nonessential; the
  Anthropic balance is not. Same asymmetry rule as the DEV_MODE gate: the broken state must
  be inert, not expensive.
- Accepted race: check-then-act means two concurrent requests can both squeak under the cap.
  The overshoot is bounded by one message's worst case (existing ceilings: MAX_TOKENS x
  MAX_TOOL_ITERS on Haiku is well under a dollar) — not worth serializing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings

log = logging.getLogger(__name__)

# $ per **million** tokens (input, output). Cache reads bill at ~0.1x input; cache WRITES at
# 1.25x input — close enough at these volumes that we price them at 0.1x/1.25x respectively.
# Verified against current published pricing 2026-07-17. When Anthropic reprices, edit here;
# history in the table stays true because it stores tokens, not dollars.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-4-8": (5.00, 25.00),
}
# An unrecognized model prices at Opus rates — the most expensive we use. Fail closed on
# price, too: a typo'd chat_model must over-count, never under-count.
_FALLBACK_PRICE = MODEL_PRICES["claude-opus-4-8"]


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    """Price a token bundle. Pure — this is the function the caps are denominated in."""
    p_in, p_out = MODEL_PRICES.get(model, _FALLBACK_PRICE)
    return (
        input_tokens * p_in
        + output_tokens * p_out
        + cache_read_input_tokens * (p_in * 0.1)
        + cache_creation_input_tokens * (p_in * 1.25)
    ) / 1_000_000


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# Two explicit queries, NOT one with `(:sub IS NULL OR principal_sub = :sub)`. The clever
# single query 42P18'd in production ("could not determine data type of parameter"): pg8000
# sends untyped parameters, and Postgres cannot infer a type for a parameter whose only
# uses are `IS NULL` and a comparison against it. The fake-DB unit tests can never catch a
# dialect error — this one was caught by check_spend_caps failing closed, exactly as designed.
_SPEND_COLS = """
    SELECT model,
           COALESCE(SUM(input_tokens), 0),
           COALESCE(SUM(output_tokens), 0),
           COALESCE(SUM(cache_read_input_tokens), 0),
           COALESCE(SUM(cache_creation_input_tokens), 0)
      FROM usage_chat_daily
     WHERE usage_date = :day
"""
_SPEND_SQL_USER = text(_SPEND_COLS + "   AND principal_sub = :sub\n GROUP BY model")
_SPEND_SQL_GLOBAL = text(_SPEND_COLS + " GROUP BY model")


def _spend_today_usd(db: Session, sub: str | None) -> float:
    """Today's priced spend — for one principal, or globally when sub is None."""
    if sub is None:
        rows = db.execute(_SPEND_SQL_GLOBAL, {"day": _today_utc()}).all()
    else:
        rows = db.execute(_SPEND_SQL_USER, {"day": _today_utc(), "sub": sub}).all()
    # SUM() over the BigInteger token columns comes back as Postgres `numeric`, which pg8000
    # hands us as `decimal.Decimal` — and `Decimal * float` (the price) raises TypeError, so
    # every chat 503'd (fails closed). Coerce to int at this DB boundary, keeping
    # estimate_cost_usd's plain-int contract. Same blind spot as the 42P18 split above: the
    # fake-DB unit tests return Python ints and can't see a driver type — the Decimal-row
    # regression test in tests/test_spend_cap.py does.
    return sum(estimate_cost_usd(m, int(i), int(o), int(cr), int(cw)) for m, i, o, cr, cw in rows)


def check_spend_caps(db: Session, principal_sub: str) -> None:
    """429 if the caller's day — or everyone's day — is spent. Call BEFORE the model loop.

    Any failure to READ the counter is also a refusal (503): a cap we cannot evaluate is a
    cap that isn't there, and this cap is the thing that makes public exposure affordable.
    """
    try:
        user_spend = _spend_today_usd(db, principal_sub)
        global_spend = _spend_today_usd(db, None)
    except HTTPException:
        raise
    except Exception:
        log.exception("spend-cap check failed — refusing chat (fails closed)")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "chat is temporarily unavailable (usage accounting is unreachable)",
        )

    if user_spend >= settings.chat_daily_user_usd:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "daily chat limit reached for this account — resets at midnight UTC",
        )
    if global_spend >= settings.chat_daily_global_usd:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "the service's daily chat budget is exhausted — resets at midnight UTC",
        )


_UPSERT_SQL = text(
    """
    INSERT INTO usage_chat_daily (principal_sub, usage_date, model,
                                  input_tokens, output_tokens,
                                  cache_read_input_tokens, cache_creation_input_tokens,
                                  message_count, principal_email)
    VALUES (:sub, :day, :model, :inp, :out, :cr, :cw, 1, :email)
    ON CONFLICT (principal_sub, usage_date, model) DO UPDATE SET
        input_tokens = usage_chat_daily.input_tokens + EXCLUDED.input_tokens,
        output_tokens = usage_chat_daily.output_tokens + EXCLUDED.output_tokens,
        cache_read_input_tokens = usage_chat_daily.cache_read_input_tokens
                                  + EXCLUDED.cache_read_input_tokens,
        cache_creation_input_tokens = usage_chat_daily.cache_creation_input_tokens
                                      + EXCLUDED.cache_creation_input_tokens,
        message_count = usage_chat_daily.message_count + 1,
        principal_email = COALESCE(EXCLUDED.principal_email,
                                   usage_chat_daily.principal_email)
    """
)


def record_chat_usage(
    db: Session,
    *,
    principal_sub: str,
    principal_email: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> None:
    """UPSERT one message's summed usage. Call AFTER the loop — including on failure paths:
    tokens spent on completed iterations are spent whether or not the last one succeeded.

    Never raises: a failed WRITE must not turn an already-delivered answer into a 500. The
    lost row under-counts by one message, which the caps' headroom absorbs; the failure is
    logged loudly instead.
    """
    try:
        db.execute(
            _UPSERT_SQL,
            {
                "sub": principal_sub, "day": _today_utc(), "model": model,
                "inp": input_tokens, "out": output_tokens,
                "cr": cache_read_input_tokens, "cw": cache_creation_input_tokens,
                "email": principal_email,
            },
        )
        db.commit()
    except Exception:
        log.exception("failed to record chat usage — one message under-counted")
