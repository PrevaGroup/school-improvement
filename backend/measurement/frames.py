"""Resolving a frame definition into a membership — the "rebuildable" half of the contract.

A definition plus a live table is not reproducible: score events keep arriving, so re-running the
query next week answers a different question. What makes an estimate reproducible is that the
definition and the events it saw both have identities, and this module is where those are computed.

Pure functions over dicts and rows. No database handle, no session — the SQL that reads score
events and writes members belongs to the caller, and keeping the decision logic separable is what
lets it be tested exhaustively without a Postgres.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from measurement.models import DEFINITION_KEYS


class UnknownDefinitionKey(ValueError):
    """A definition carrying a key the resolver does not understand.

    Deliberately fatal rather than ignored. A typo in a frame definition that is silently skipped
    produces a frame that admits more than its author intended, and the resulting estimate looks
    perfectly healthy — this is the same failure the eval design refuses when it makes an unknown
    grader return `na` with a visible note rather than pass quietly.
    """


def canonical(definition: Mapping[str, Any]) -> str:
    """A byte-stable rendering of a definition.

    Sorted keys, sorted list values, no incidental whitespace. Two definitions that admit the same
    observations must hash the same however they were typed, or the hash reports edits nobody made.
    """
    def norm(v: Any) -> Any:
        if isinstance(v, (list, tuple, set)):
            return sorted(norm(x) for x in v)
        if isinstance(v, Mapping):
            return {k: norm(v[k]) for k in sorted(v)}
        return v

    return json.dumps({k: norm(definition[k]) for k in sorted(definition)},
                      separators=(",", ":"), ensure_ascii=False)


def definition_hash(definition: Mapping[str, Any]) -> str:
    """The identity of a definition. Stored on the frame; a mismatch says the definition moved."""
    validate(definition)
    return hashlib.sha256(canonical(definition).encode("utf8")).hexdigest()


def validate(definition: Mapping[str, Any]) -> None:
    unknown = sorted(set(definition) - set(DEFINITION_KEYS))
    if unknown:
        raise UnknownDefinitionKey(
            f"frame definition carries unknown key(s): {unknown}. "
            f"Known keys: {sorted(DEFINITION_KEYS)}. A key the resolver does not understand "
            f"would be silently ignored, and the frame would admit more than intended.")


def admits(definition: Mapping[str, Any], event: Mapping[str, Any]) -> bool:
    """Whether one score event belongs in the frame this definition describes.

    Absent keys mean "no constraint on this dimension" — a definition names what it restricts, so
    an empty definition admits everything and each key narrows. The alternative (defaults that
    exclude) makes a definition's meaning depend on the resolver's version, which is exactly the
    reproducibility the frame exists to provide.
    """
    validate(definition)

    def within(key: str, value: Any) -> bool:
        allowed = definition.get(key)
        return allowed is None or value in allowed

    if not within("windows", event.get("window_label")):
        return False
    if not within("node_ids", event.get("node_id")):
        return False
    if not within("scorer_types", event.get("scorer_type")):
        return False
    if not within("iterations", event.get("iteration")):
        return False

    if definition.get("measurement_occasions_only") and not event.get("is_measurement_occasion"):
        return False

    # Escalated and unescalated scores come from different administrations of the same rater, so
    # admitting them is a decision rather than a default. Absent means admit — the conservative
    # reading belongs in the definition an author writes, not in a silent resolver default.
    if definition.get("include_escalated") is False and (event.get("scrutiny_passes") or 1) > 1:
        return False
    # A set-level override is ONE judgment covering many artifacts. Admitting every covered row
    # multiplies a single decision against everyone else's.
    if definition.get("include_set_overrides") is False and event.get("set_override_id"):
        return False

    lo, hi = definition.get("min_scrutiny_passes"), definition.get("max_scrutiny_passes")
    passes = event.get("scrutiny_passes") or 1
    if lo is not None and passes < lo:
        return False
    if hi is not None and passes > hi:
        return False

    return True


def resolve(definition: Mapping[str, Any],
            events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The membership this definition resolves to over these events.

    `enters_calibration` is carried from the event rather than recomputed. It is stamped at write
    time as the authoritative answer to a question the frame does not get to revisit: the frame
    decides what is measurable, the event decides what moves parameters.
    """
    return [{"event_id": e["event_id"],
             "enters_calibration": bool(e.get("enters_calibration"))}
            for e in events if admits(definition, e)]
