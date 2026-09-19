"""Span verification — the deterministic gate.

Moved here from the slice-1 prototype unchanged. Deliberately unchanged: it is the piece that was
actually exercised against real papers, and a rewrite on the way into the repo would have thrown
away the only part of the pipeline with evidence behind it.

A proposed span survives only if it is an exact substring of the text it claims to come from.
No model is involved and none should be: this is the single largest error reduction in the
pipeline (fabricated or paraphrased evidence presented as quotation), and it is string matching.

Normalization is versioned, because it changes what the scorer sees. Widening it is a change to
the administration, not to the rater, and it demands the same anchor replay — so a rule is added
here only with a reason, and NORM_VERSION moves when one is.
"""
from __future__ import annotations
import re
import unicodedata

NORM_VERSION = "1"

# Typographic substitutions only. Each maps a character a model reliably emits onto the one the
# source actually contains, and none of them changes which words are present.
_SUBS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ",
    "…": "...",
}


def normalize(s: str) -> str:
    """Fold typography and collapse whitespace. Deliberately does NOT fold case or strip
    punctuation: a scorer shown 'the court' where the student wrote 'the Court' is being shown
    something the student did not write, and quotation accuracy is part of what is scored."""
    s = unicodedata.normalize("NFC", s)
    for a, b in _SUBS.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def verify(span: str, *sources: str) -> dict:
    """Confirm `span` appears verbatim in any of `sources`.

    Returns the verdict plus the offset, so a caller can highlight without searching again and a
    reviewer can see exactly what was matched. `ok=False` is not an error condition — it is the
    normal outcome for a fabricated quotation, and dropping it is the point.
    """
    n = normalize(span)
    if not n:
        return {"ok": False, "reason": "empty span", "norm": n}
    for idx, src in enumerate(sources):
        at = normalize(src).find(n)
        if at != -1:
            return {"ok": True, "source": idx, "at": at, "len": len(n), "norm": n}
    return {"ok": False, "reason": "not found in any source", "norm": n}


def verify_all(spans: list[str], *sources: str) -> tuple[list[dict], list[dict]]:
    """Split proposed spans into kept and dropped. Both are returned: a criterion left with no
    verified span routes to abstention rather than to a low score, and the reviewer needs to see
    what was dropped to tell those apart."""
    kept, dropped = [], []
    for s in spans:
        v = verify(s, *sources)
        (kept if v["ok"] else dropped).append({"span": s, **v})
    return kept, dropped
