"""How close two raters are, in the statistics the field actually asks for.

MFRM answers WHY the scores differ — severity, fit, bias. These answer HOW MUCH they differ, in
numbers that are comparable to published work on the same corpus. Both are needed and neither
replaces the other: a quadratic weighted kappa of 0.68 is meaningless without knowing whether the
gap is a constant offset or unpredictable disagreement, and a severity of +0.4 logits is
meaningless to anyone who has only ever read kappas.

Pure functions over pairs, no database handle — the same split as `frames.py`, so every one of
these can be checked against hand-worked examples.

## Why quadratic weighting

On an ordered scale, scoring a 6 as a 5 is not the same mistake as scoring it a 1, and unweighted
kappa treats them identically. Quadratic weights are the convention for exactly this corpus, which
matters more than their theoretical merit: a number that cannot be compared to the published ASAP
and PERSUADE results is a number nobody can place.

## Why exact and adjacent are reported beside it

Kappa is a single number that hides its shape. Exact agreement and adjacent agreement are what a
teacher can actually picture — "it agreed outright on half of them and was within one on nine in
ten" — and they are what distinguishes a rater that is usually right from one that is never far
wrong. The confusion matrix is reported for the same reason: compression toward the middle of a
scale is invisible in kappa and obvious in a matrix.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Agreement:
    n: int
    categories: list[int]
    exact: float
    adjacent: float
    qwk: float
    linear_kappa: float
    # Mean signed difference, ours minus theirs. Positive means we score HIGHER — the opposite
    # sign convention from severity, where positive means harsher, and named to avoid the
    # confusion rather than assuming nobody will make it.
    mean_signed: float
    mean_absolute: float
    matrix: dict = field(default_factory=dict)
    # How much of each rater's range is actually used. A rater that never gives a 1 or a 6 has
    # compressed the scale, and kappa hides that completely.
    spread: dict = field(default_factory=dict)

    @property
    def compressed(self) -> bool:
        """Do we use a narrower range than the humans did?"""
        return self.spread.get("ours_sd", 0) < self.spread.get("theirs_sd", 0) * 0.8


def _matrix(pairs: list[tuple[int, int]], cats: list[int]) -> dict:
    m = {a: {b: 0 for b in cats} for a in cats}
    for theirs, ours in pairs:
        m[theirs][ours] += 1
    return m


def _sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _kappa(pairs: list[tuple[int, int]], cats: list[int], *, quadratic: bool) -> float:
    """Weighted kappa. `quadratic` squares the distance; otherwise it is linear.

    ## Weights come from the score values, not from position in the category list

    Textbook weighted kappa indexes categories by position, which is identical to using the values
    on a contiguous scale and differs the moment the sample has a hole in it. If nobody in a
    per-trait split scored a 4, position weighting makes a 3-versus-5 disagreement adjacent rather
    than two apart, and the rater scores better for a gap in the sample.

    Using the values anchors the statistic to the rubric instead of to the sample, so the same
    disagreements always earn the same number. On a complete scale the two are the same thing,
    which is why this reads as conventional QWK against published work.

    Returns nan rather than a number when the scale collapses to one category — kappa is
    undefined there, and 0.0 would read as "no agreement" when the truth is "no question was
    asked".
    """
    n, k = len(pairs), len(cats)
    if n == 0 or k < 2:
        return float("nan")
    idx = {c: i for i, c in enumerate(cats)}
    # Any common factor on the weights cancels between the observed and expected sums, so the
    # normaliser is presentational only. Kept so a printed weight is 0..1 as the literature has it.
    span = cats[-1] - cats[0]
    denom = (span ** 2 if quadratic else span) or 1

    obs = [[0.0] * k for _ in range(k)]
    for theirs, ours in pairs:
        obs[idx[theirs]][idx[ours]] += 1 / n

    row = [sum(obs[i]) for i in range(k)]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    num = den = 0.0
    for i in range(k):
        for j in range(k):
            d = cats[i] - cats[j]
            w = (d ** 2 if quadratic else abs(d)) / denom
            num += w * obs[i][j]
            den += w * row[i] * col[j]
    if den == 0:
        # Both raters used exactly one category, and the same one. Perfect agreement with no
        # information in it; nan rather than 1.0, which would be a claim about a rater.
        return float("nan")
    return 1 - num / den


def compare(pairs: list[tuple[int, int]], categories: list[int] | None = None) -> Agreement:
    """`pairs` is [(human, model), ...] as ordered category values.

    Categories are supplied rather than inferred wherever possible — for the CONFUSION MATRIX, and
    not for kappa, which was the reason I first wrote down and it was wrong.

    Kappa here does not move when the category list is padded or trimmed. Weights are taken from
    the score values (see `_kappa`), a common factor on them cancels between the observed and
    expected sums, and a category nobody used has a zero marginal and contributes to neither. So
    "they never gave a 6" changes the statistic not at all.

    The matrix is a different matter, and it is the one that carries the finding. Printed only over
    the values a rater actually used, it always looks like full coverage of the scale — the unused
    rows are exactly where compression toward the middle is visible, so they have to be there.
    """
    pairs = [(int(a), int(b)) for a, b in pairs if a is not None and b is not None]
    if not pairs:
        return Agreement(0, categories or [], float("nan"), float("nan"), float("nan"),
                         float("nan"), float("nan"), float("nan"))

    cats = sorted(categories) if categories else sorted(
        {c for p in pairs for c in p})
    theirs = [a for a, _ in pairs]
    ours = [b for _, b in pairs]
    diffs = [b - a for a, b in pairs]

    return Agreement(
        n=len(pairs),
        categories=cats,
        exact=sum(1 for d in diffs if d == 0) / len(pairs),
        adjacent=sum(1 for d in diffs if abs(d) <= 1) / len(pairs),
        qwk=_kappa(pairs, cats, quadratic=True),
        linear_kappa=_kappa(pairs, cats, quadratic=False),
        mean_signed=sum(diffs) / len(diffs),
        mean_absolute=sum(abs(d) for d in diffs) / len(diffs),
        matrix=_matrix(pairs, cats),
        spread={"ours_sd": round(_sd(ours), 3), "theirs_sd": round(_sd(theirs), 3),
                "ours_used": sorted(set(ours)), "theirs_used": sorted(set(theirs))},
    )


def render(a: Agreement, *, label: str = "") -> str:
    """The numbers, and the matrix under them. Meant to be read rather than parsed."""
    if not a.n:
        return f"{label}: no pairs"
    lines = [f"{label}  n={a.n}",
             f"  exact {a.exact:.1%}   within one {a.adjacent:.1%}",
             f"  QWK {a.qwk:.3f}   linear kappa {a.linear_kappa:.3f}",
             f"  mean signed {a.mean_signed:+.2f}  (positive = we score higher)",
             f"  mean absolute {a.mean_absolute:.2f}"]
    if a.compressed:
        # Named rather than left to be spotted in the matrix: it is the failure mode a kappa
        # cannot show, and the one most likely on this scale.
        lines.append(f"  COMPRESSED: our SD {a.spread['ours_sd']} against theirs "
                     f"{a.spread['theirs_sd']} — we are using less of the scale than they did")
    header = "      ours:" + "".join(f"{c:>5}" for c in a.categories)
    lines += ["", header]
    for t in a.categories:
        row = a.matrix.get(t, {})
        lines.append(f"  human {t}:" + "".join(f"{row.get(o, 0):>5}" for o in a.categories))
    return "\n".join(lines)
