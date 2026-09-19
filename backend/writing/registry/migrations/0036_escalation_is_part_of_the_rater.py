"""re-stamp `definition_hash` now that escalation is part of the rater

Migration 0027 added the `escalation` column and deliberately left it out of `definition_hash`,
writing the counter-argument down rather than winning it:

    two configurations that differ only in budget do produce different bodies of scores, and
    someone doing a strict replay would want them to hash differently. Including it would mean
    that raising a budget re-rates every paper ever scored. That is a bigger call than this
    migration should make quietly.

The call has now been made, by the person entitled to make it: the harness is the rater. Models,
prompts, normalisation, injected guidance, and how deep the thing may look are one apparatus, and
severity is a property of the apparatus rather than of the model inside it.

## What changes

`definition_hash` now covers the RESOLVED escalation policy. Resolved, not the raw column, so a
NULL escalation and one spelling out the defaults hash identically — they are the same rater and
only one of them says so out loud.

Every existing row's stored hash therefore no longer matches its parts, so this re-stamps them.
Without that, nothing loads: `check_configuration` now compares the stored hash to the computed
one, which is the second half of this change and arguably the larger half — the column has existed
since 0012 and was documented as the thing that catches a configuration edited in place, and
nothing ever compared it to anything. A guard that is never evaluated is not a guard.

## Why the hash is recomputed here rather than by calling the application

A migration must reproduce the hash AS OF THIS REVISION. Importing `scoring.rater` would make this
file's behaviour depend on code that keeps changing, so a replay of the migration history would
stamp whatever today's definition happens to be. It is also an import `registry` may not make.

So the computation is inlined. `tests/test_identity_hash_agrees.py` is what keeps the live copies
in step; this one is frozen on purpose.

## What it does NOT do

It does not re-score anything, and it does not invalidate the anchor severity estimated before it.
Those scores were produced by a specific apparatus; what changes is that the apparatus is now
described completely. `score_event.scoring_configuration_id` still points at the same row, and the
per-event stamps — `scrutiny_passes`, `escalation_trigger`, the escalated `effort` — say what
actually happened, exactly as 0027 said they would.

Revision ID: 0036
Revises: 0035
"""
from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

# `scoring.escalate.Policy()` defaults, frozen at this revision. See above for why this is a copy.
_DEFAULT_POLICY = {"budget": 2,
                   "triggers": ["abstained", "no_verified_evidence"],
                   "escalated_effort": "high",
                   "terminal_action": "route_to_human"}


def _resolve(raw: dict | None) -> dict:
    """`Policy.from_config(raw).as_dict()`, frozen. Absent means the default."""
    if not raw:
        return dict(_DEFAULT_POLICY)
    return {"budget": int(raw.get("budget", _DEFAULT_POLICY["budget"])),
            "triggers": list(raw.get("triggers") or _DEFAULT_POLICY["triggers"]),
            "escalated_effort": str(raw.get("escalated_effort")
                                    or _DEFAULT_POLICY["escalated_effort"]),
            "terminal_action": str(raw.get("terminal_action")
                                   or _DEFAULT_POLICY["terminal_action"])}


def _hash(model_id, effort, prompt_versions, normalization_version, escalation) -> str:
    return hashlib.sha256(
        json.dumps({"model_id": model_id, "effort": effort,
                    "prompt_versions": prompt_versions,
                    "normalization_version": normalization_version,
                    "escalation": escalation},
                   sort_keys=True, separators=(",", ":")).encode("utf8")).hexdigest()[:32]


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("""
        SELECT config_id, model_id, effort, prompt_versions, normalization_version, escalation
          FROM registry_scoring_configuration
    """)).mappings().all()

    for r in rows:
        conn.execute(
            sa.text("""UPDATE registry_scoring_configuration
                          SET definition_hash = :h
                        WHERE config_id = :c"""),
            {"h": _hash(r["model_id"], r["effort"], r["prompt_versions"],
                        r["normalization_version"], _resolve(r["escalation"])),
             "c": r["config_id"]})


def downgrade() -> None:
    # Re-stamp without escalation, so a downgraded database matches a downgraded codebase. The
    # hashes are derived from the parts either way — nothing here is lost, only recomputed.
    conn = op.get_bind()
    rows = conn.execute(sa.text("""
        SELECT config_id, model_id, effort, prompt_versions, normalization_version
          FROM registry_scoring_configuration
    """)).mappings().all()

    for r in rows:
        h = hashlib.sha256(
            json.dumps({"model_id": r["model_id"], "effort": r["effort"],
                        "prompt_versions": r["prompt_versions"],
                        "normalization_version": r["normalization_version"]},
                       sort_keys=True, separators=(",", ":")).encode("utf8")).hexdigest()[:32]
        conn.execute(
            sa.text("""UPDATE registry_scoring_configuration
                          SET definition_hash = :h WHERE config_id = :c"""),
            {"h": h, "c": r["config_id"]})
