"""The Claude spend cap (§3.4) — the last gate blocker before --no-allow-unauthenticated.

The property under test: /api/chat cannot spend Anthropic money past two daily budgets, and
when the accounting layer is broken it refuses rather than pours. No DB and no model calls —
the SQL layer is faked at exactly the seam app/usage.py reads through, so what's pinned is
the pricing math, the cap decisions, and the fail-closed behavior.
"""
import pytest
from fastapi import HTTPException

from app import usage
from app.usage import check_spend_caps, estimate_cost_usd


# --------------------------------------------------------------------------- #
# pricing — the caps are denominated in this function's output
# --------------------------------------------------------------------------- #
def test_haiku_pricing_matches_published_rates():
    """$1/MTok in, $5/MTok out. 1M of each = $6.00 exactly."""
    assert estimate_cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000) == pytest.approx(6.00)


def test_opus_pricing_matches_published_rates():
    """$5/MTok in, $25/MTok out — 5x Haiku. This gap is WHY the counter stores model."""
    assert estimate_cost_usd("claude-opus-4-8", 1_000_000, 1_000_000) == pytest.approx(30.00)


def test_unknown_model_prices_at_opus_rates_fail_closed():
    """A typo'd chat_model must OVER-count, never under-count. Pricing an unknown model at
    Haiku rates would let a misconfiguration quietly quintuple real spend under the cap."""
    assert estimate_cost_usd("claude-nonexistent-9", 1_000_000, 1_000_000) == pytest.approx(30.00)


def test_cache_reads_bill_at_a_tenth_of_input():
    """The chat loop resends history every iteration; cache reads are most of its input.
    Billing them at full input price would overstate spend ~10x and starve real users."""
    assert estimate_cost_usd("claude-haiku-4-5", 0, 0, cache_read_input_tokens=1_000_000) \
        == pytest.approx(0.10)


def test_a_realistic_message_costs_cents_not_dollars():
    """Sanity-pin the scale the caps were sized against: a heavy 6-iteration Haiku message
    (~30k in, 3k out each) lands around a dime, so $2/day is ~10-40 heavy messages."""
    cost = sum(estimate_cost_usd("claude-haiku-4-5", 30_000, 3_000) for _ in range(6))
    assert 0.01 < cost < 0.50


# --------------------------------------------------------------------------- #
# cap decisions — fake the SQL seam, pin the branch logic
# --------------------------------------------------------------------------- #
class _FakeDB:
    """Stands in for the Session at the exact seam usage.py reads: execute(...).all()
    returning (model, in, out, cache_read, cache_write) rows. The user-scoped query binds
    :sub; the global one doesn't (two separate statements — the merged one 42P18'd on pg8000)."""

    def __init__(self, user_rows, global_rows):
        self._user, self._global = user_rows, global_rows

    def execute(self, _sql, params):
        rows = self._user if "sub" in params else self._global
        return type("R", (), {"all": lambda self_: rows})()


def _tokens_costing(usd: float) -> int:
    """Haiku output tokens summing to `usd` — output is $5/MTok, so usd/5 MTok."""
    return int(usd / 5.00 * 1_000_000)


def test_under_both_caps_passes(monkeypatch):
    monkeypatch.setattr(usage.settings, "chat_daily_user_usd", 2.00)
    monkeypatch.setattr(usage.settings, "chat_daily_global_usd", 20.00)
    row = ("claude-haiku-4-5", 0, _tokens_costing(0.50), 0, 0)
    check_spend_caps(_FakeDB([row], [row]), "uid-1")  # must not raise


def test_user_cap_429s_the_spender_only(monkeypatch):
    monkeypatch.setattr(usage.settings, "chat_daily_user_usd", 2.00)
    monkeypatch.setattr(usage.settings, "chat_daily_global_usd", 20.00)
    over = ("claude-haiku-4-5", 0, _tokens_costing(2.50), 0, 0)
    with pytest.raises(HTTPException) as e:
        check_spend_caps(_FakeDB([over], [over]), "uid-1")
    assert e.value.status_code == 429
    assert "this account" in e.value.detail  # blames the account, not the service


def test_global_cap_429s_even_a_fresh_user(monkeypatch):
    """The cap that actually bounds exposure: per-user x allowlisted-user-count. A user who
    has spent nothing still gets 429 when the day's global budget is gone."""
    monkeypatch.setattr(usage.settings, "chat_daily_user_usd", 2.00)
    monkeypatch.setattr(usage.settings, "chat_daily_global_usd", 20.00)
    everyone = ("claude-haiku-4-5", 0, _tokens_costing(25.0), 0, 0)
    with pytest.raises(HTTPException) as e:
        check_spend_caps(_FakeDB([], [everyone]), "fresh-uid")
    assert e.value.status_code == 429
    assert "daily chat budget" in e.value.detail


def test_summed_token_columns_arrive_as_decimal_and_still_price(monkeypatch):
    """REGRESSION (prod chat 503, 2026-07-16→17): Postgres SUM() of bigint returns `numeric`,
    which pg8000 hands us as `decimal.Decimal`. `Decimal * float(price)` raised TypeError inside
    estimate_cost_usd, so check_spend_caps failed closed and every message 503'd.

    The other tests here return Python ints (the fake DB can't reproduce a driver type — the
    same reason the 42P18 slipped through), so this one feeds Decimals at the exact seam. A
    priced-correctly result (this $5 day trips the $2 user cap → 429, NOT 503) proves the fix."""
    from decimal import Decimal

    monkeypatch.setattr(usage.settings, "chat_daily_user_usd", 2.00)
    monkeypatch.setattr(usage.settings, "chat_daily_global_usd", 20.00)
    # 1M Haiku output tokens = $5.00, expressed as the driver returns a SUM: Decimal.
    row = ("claude-haiku-4-5", Decimal("0"), Decimal("1000000"), Decimal("0"), Decimal("0"))
    with pytest.raises(HTTPException) as e:
        check_spend_caps(_FakeDB([row], [row]), "uid-1")
    assert e.value.status_code == 429  # priced fine over the cap — NOT a 503 from a TypeError


def test_broken_accounting_refuses_rather_than_pours(monkeypatch):
    """FAILS CLOSED — the load-bearing property. A cap we cannot evaluate is a cap that
    isn't there, and this cap is what makes public exposure affordable. Same asymmetry rule
    as the DEV_MODE gate: the broken state must be inert, not expensive."""
    class _DeadDB:
        def execute(self, *_a, **_k):
            raise ConnectionError("postgres is having a day")

    with pytest.raises(HTTPException) as e:
        check_spend_caps(_DeadDB(), "uid-1")
    assert e.value.status_code == 503


def test_multi_model_days_price_each_model_at_its_own_rate(monkeypatch):
    """(user, day, MODEL) grain exists for this: $1.50 of Haiku + $1.00 of Opus = $2.50,
    over a $2 cap — flattening models to one row would misprice one of them."""
    monkeypatch.setattr(usage.settings, "chat_daily_user_usd", 2.00)
    monkeypatch.setattr(usage.settings, "chat_daily_global_usd", 100.00)
    rows = [
        ("claude-haiku-4-5", 0, _tokens_costing(1.50), 0, 0),
        ("claude-opus-4-8", 0, int(1.00 / 25.00 * 1_000_000), 0, 0),
    ]
    with pytest.raises(HTTPException) as e:
        check_spend_caps(_FakeDB(rows, rows), "uid-1")
    assert e.value.status_code == 429
