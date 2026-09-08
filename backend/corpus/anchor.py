"""Choosing the anchor papers: deterministic, stratified, and scored in nested waves.

The anchor set is what model severity is estimated against and what a new scoring configuration is
replayed on before promotion. Both of those are claims about a FIXED set of papers, so how the set
was chosen has to be reproducible from the corpus alone — the same reasoning as `partition_for`,
one level down. A set drawn by `ORDER BY random() LIMIT 300` cannot be replayed, and "we replayed
the anchor set" is then a claim nobody can check.

## Why stratified, and on what

Two facts about PERSUADE decide this, both measured rather than assumed:

    ELL status is 8.6% of the corpus. A simple random draw of 600 papers yields ~52 ELL papers,
    which is badly underpowered for the one analysis the corpus exists to make possible.

    Human scores concentrate in the middle: 3s and 4s are 58% of the corpus, 6s are 3.4% and 1s
    are 4.0%. A random draw is mostly middle, and the extremes are where a rater's fit statistics
    are informative — outfit is driven by unexpected responses, which live at the ends.

So the strata are ELL status × human score. Not race or economic status: those matter and are
analysed, but stratifying on five variables at once produces cells of four papers, and a cell too
small to measure is worse than an unstratified draw because it looks like coverage.

## The cell that cannot be filled

There are FOUR ELL papers scored 6 in the whole corpus, and 70 scored 5. No sample size fixes
that. `select` takes what exists, reports the shortfall per cell, and the report is the point: a
DIF claim at the top of the scale is unavailable from this corpus, and that has to be stated
rather than discovered when somebody reads a confidence interval.

## Waves are nested, not separate samples

Scoring 300 now and 300 more later must produce ONE sample of 600, not two samples of 300. So
wave membership is a property of a paper's rank within its cell, computed once: wave 1 is the
first n papers of every cell, wave 2 extends the same ordering. Expanding never re-draws, and the
first wave's scores stay usable.

## Calibration only

Drawn from the calibration partition, leaving validation untouched. Estimating severity on papers
and then validating a claim on the same papers is circular, and the partition exists so that the
holdout survives decisions like this one being made in a hurry.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# Same shape as `_PARTITION_SALT`: a named constant, so a change to the draw is a visible edit
# rather than a silent reshuffle. Changing this invalidates every anchor claim made before it.
_ANCHOR_SALT = "corpus-anchor-v1"

SCORES = ("1", "2", "3", "4", "5", "6")
ELL = ("Yes", "No")


@dataclass
class Cell:
    """One stratum, what it wanted, and what it could give."""
    ell: str
    score: str
    wanted: int
    available: int
    taken: int

    @property
    def short(self) -> int:
        return max(0, self.wanted - self.taken)


@dataclass
class Draw:
    paper_ids: list[str] = field(default_factory=list)
    cells: list[Cell] = field(default_factory=list)
    waves: dict[str, int] = field(default_factory=dict)   # paper_id -> wave

    @property
    def shortfalls(self) -> list[Cell]:
        """Cells that could not be filled. Named, because a DIF claim in a short cell is not
        underpowered by chance — it is unavailable, and the difference matters to a reader."""
        return [c for c in self.cells if c.short]

    def wave(self, n: int) -> list[str]:
        return [p for p in self.paper_ids if self.waves[p] <= n]


def rank_key(paper_id: str) -> str:
    """Deterministic ordering within a cell.

    Hash rather than row order or a seeded shuffle: the same corpus must produce the same anchor
    set on a different machine and after a reload, and row order is an artefact of how the CSV was
    written.
    """
    return hashlib.sha256(f"{_ANCHOR_SALT}:{paper_id}".encode()).hexdigest()


def select(papers: list[dict], per_cell: dict[str, int] | int,
           *, waves: tuple[int, ...] = ()) -> Draw:
    """Stratified draw over ELL × human score.

    `papers` carries `paper_id`, `ell_status`, `score` and `partition`; only calibration papers are
    eligible. `per_cell` is a target per stratum — an int for all cells, or a dict keyed by score
    so the thin top of the scale can ask for less than the middle.

    `waves` gives the per-cell size of each wave, cumulatively: `(30, 60)` means wave 1 takes the
    first 30 of every cell and wave 2 extends to 60. Wave membership is a property of rank, so
    wave 1 is always a subset of wave 2 and expanding never re-draws.
    """
    target = ((lambda s: per_cell) if isinstance(per_cell, int)
              else (lambda s: per_cell.get(s, 0)))

    by_cell: dict[tuple[str, str], list[dict]] = {}
    for p in papers:
        if p.get("partition") != "calibration":
            continue
        ell, score = str(p.get("ell_status") or ""), str(p.get("score") or "")
        if ell not in ELL or score not in SCORES:
            # A paper with no ELL label or no human score cannot sit in a stratum. Excluded rather
            # than bucketed as "unknown", because absence of a label is not a label — the same rule
            # the loader applies when it keeps a blank demographic NULL.
            continue
        by_cell.setdefault((ell, score), []).append(p)

    out = Draw()
    for ell in ELL:
        for score in SCORES:
            pool = sorted(by_cell.get((ell, score), []), key=lambda p: rank_key(p["paper_id"]))
            want = target(score)
            take = pool[:want]
            out.cells.append(Cell(ell=ell, score=score, wanted=want,
                                  available=len(pool), taken=len(take)))
            for i, p in enumerate(take):
                out.paper_ids.append(p["paper_id"])
                # Rank decides the wave, so the waves nest. Anything past the last declared wave
                # is in the final one.
                out.waves[p["paper_id"]] = next(
                    (w + 1 for w, size in enumerate(waves) if i < size), len(waves) or 1)
    return out


def report(draw: Draw) -> str:
    """What was drawn, per cell, including what could not be. Meant to be read before spending."""
    lines = ["cell            wanted  available  taken",
             "----            ------  ---------  -----"]
    for c in draw.cells:
        flag = "  ← short" if c.short else ""
        lines.append(f"ELL={c.ell:<3} score={c.score}  {c.wanted:>6}  {c.available:>9}  "
                     f"{c.taken:>5}{flag}")
    lines.append(f"\n{len(draw.paper_ids)} papers")
    if draw.shortfalls:
        lines.append(
            "\nCells that could not be filled — a claim about these strata is UNAVAILABLE from "
            "this corpus, not merely underpowered:")
        for c in draw.shortfalls:
            lines.append(f"  ELL={c.ell} score={c.score}: wanted {c.wanted}, "
                         f"the corpus has {c.available}")
    return "\n".join(lines)
