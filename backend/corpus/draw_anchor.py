"""Draw the anchor set and print it, before any of it is scored.

    python -m corpus.draw_anchor --wave1 30 --wave2 60

Prints the per-cell table and the shortfalls, and nothing else happens. Reading what a sample
WOULD be before paying to score it is the cheap half of this, and the half most easily skipped:
the ELL × score-6 cell holds four papers in the entire corpus, and that is better learned here
than from a confidence interval three weeks later.

Selection is deterministic (`corpus.anchor`), so this command is safe to run repeatedly and
prints the same set every time. It writes nothing — the anchor set is a function of the corpus,
not a stored list, which is what makes "we replayed the anchor set" checkable.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from ._db import _engine
from .anchor import report, select

# The corpus's own human score, joined per paper. `kind = 'holistic'` because that is the only
# kind PERSUADE ships — naming it means a corpus that later ships trait scores does not silently
# change what this stratifies on.
_PAPERS = text("""
    SELECT p.paper_id, p.ell_status, p.partition, s.value::text AS score
      FROM corpus_paper p
      JOIN corpus_score s ON s.paper_id = p.paper_id AND s.kind = 'holistic'
     WHERE p.source_id = :source_id
""")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default="persuade20")
    ap.add_argument("--wave1", type=int, default=30, help="papers per cell in the first wave")
    ap.add_argument("--wave2", type=int, default=60, help="cumulative per cell after wave 2")
    ap.add_argument("--json", action="store_true", help="paper ids, for piping into a scorer")
    a = ap.parse_args()

    with _engine().connect() as conn:
        papers = [dict(r) for r in conn.execute(
            _PAPERS, {"source_id": a.source}).mappings()]
    # The score arrives as a numeric; the strata are strings. Normalised here rather than in the
    # query so the selection stays a pure function over plain dicts.
    for p in papers:
        p["score"] = str(p["score"]).split(".")[0]

    draw = select(papers, a.wave2, waves=(a.wave1, a.wave2))
    if a.json:
        print(json.dumps({"wave1": draw.wave(1), "wave2": draw.wave(2)}, indent=1))
        return

    print(f"{len(papers):,} papers with a holistic score in {a.source}\n")
    print(report(draw))
    print(f"\nwave 1: {len(draw.wave(1)):,} papers  ·  wave 1+2: {len(draw.wave(2)):,} papers")
    print("\nNothing has been scored. `--json` emits the ids.")


if __name__ == "__main__":
    main()
