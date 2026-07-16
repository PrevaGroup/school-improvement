"""Operational state owned by core — platform bookkeeping, not a module's data product.

This file exists to make a seam decision explicit (docs/MODULES.md): `serving` owns no
tables, and the spend counter does not change that. `usage_chat_daily` is infrastructure —
like `dim_tenant`, it belongs to the platform, not to the module that happens to write it.
`serving` may WRITE it the same way it may call `SET LOCAL app.tenant`: through core.

Not tenant data, so no RLS: rows are keyed by the verified principal (`sub` from the ID
token), never by district, and never served through the API.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UsageChatDaily(Base):
    """Per-user, per-model, per-UTC-day Anthropic token usage for /api/chat.

    Raw facts only — token counts as the API reported them. Dollar cost is DERIVED at read
    time from the price table in app/usage.py, never stored: prices change (Sonnet 5's intro
    pricing expires 2026-08-31, for one), and baking a valuation into the fact would make
    history lie when they do. Same reasoning as fact_metric never storing a computed metric.
    """
    __tablename__ = "usage_chat_daily"

    principal_sub: Mapped[str] = mapped_column(Text, primary_key=True)   # verified token `sub`
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)     # UTC day
    model: Mapped[str] = mapped_column(Text, primary_key=True)           # e.g. claude-haiku-4-5

    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cache_read_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cache_creation_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    principal_email: Mapped[str | None] = mapped_column(Text)  # denormalized, ops queries only
