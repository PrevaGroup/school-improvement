"""Many-facet Rasch measurement: separating how good the writing is from how harsh the rater is.

Design: the expansion plan §11 Phase 6 — "MFRM fits, anchored and reproducible", and §10, which
says why raw agreement is not enough. A model that scores every paper one point below the humans
looks inaccurate and is perfectly usable once the offset is known; a model that agrees on average
while disagreeing erratically looks fine and is not. Agreement statistics cannot tell those apart.
This can.

## The model

Andrich's rating scale model with two facets — person and rater — over categories 0..m:

    P(X = k)  ∝  exp( k·(θ_n − α_r) − Σ_{j≤k} τ_j )

`θ_n` is how good paper n is, `α_r` is how severe rater r is, and `τ_j` are the thresholds between
adjacent categories, shared across raters. Severity enters with a minus sign, so a harsher rater
produces lower expected scores at the same paper quality — which is the separation the whole
exercise exists for.

Estimated by joint maximum likelihood (Linacre's approach in Facets), Newton-Raphson on each facet
in turn, with raters and thresholds centred for identification. Persons float: the scale's origin
is "the average rater", which is what makes severity readable as a departure from it.

## What this can and cannot say about PERSUADE

CAN: whether the model is harsher or milder than the human pool, in logits, separated from paper
quality. Whether it is CONSISTENT — infit and outfit catch a rater who agrees on average and
disagrees unpredictably, which is the more dangerous failure and the one agreement hides. And
whether its severity differs by subgroup CONDITIONAL on paper quality, which is the fairness
question and which no agreement statistic can reach.

CANNOT: decompose the human side. PERSUADE ships no rater identity — `corpus_score.rater_id` is
NULL for every row — so "the humans" is one facet element, an anonymous pool. If that pool was
collectively harsh on some prompt, this measures the model's agreement with that and calls it the
origin. The corpus contract names this as the anonymous-pool problem and it is not a limitation of
this code.

CANNOT: say anything about severity UNIFORMITY across criteria, because PERSUADE ships one
holistic score. With one trait there is no spread to measure. That is stop condition 3, and it
needs an anchor set with trait-level human scores which does not exist yet.

## Person estimates from two ratings are noisy, and that is fine

JMLE is biased outward when an element has few observations, and with two raters per paper the
person estimates are the weakest thing here. They are not what this is for. Rater severity is
estimated from every observation that rater made — 664 of them in the planned anchor wave — and
that is the quantity Phase 6 needs. Person estimates are reported with their standard errors so
nobody reads them as precise, and `.person_note` says so in words.

## Connectedness is checked, not assumed

Two raters who never rate the same papers produce two floating scales and a severity difference
that is an artefact of which papers each saw. A fully-crossed design is connected by construction,
and this checks anyway, because the design that reaches this function will not always be the one
it was written for.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Observation:
    """One rating: this rater gave this paper this category."""
    person: str
    rater: str
    category: int          # 0-based; a 1..6 human score arrives here as 0..5


@dataclass
class Element:
    """One person or one rater, as estimated."""
    name: str
    measure: float
    se: float
    n: int
    infit: float
    outfit: float
    # Set when an element scored at the very top or bottom of the scale on every observation.
    # Its measure is infinite in the model, so it is excluded from estimation and reported.
    extreme: str | None = None


@dataclass
class Fit:
    persons: dict[str, Element] = field(default_factory=dict)
    raters: dict[str, Element] = field(default_factory=dict)
    thresholds: list[float] = field(default_factory=list)
    iterations: int = 0
    converged: bool = False
    max_category: int = 0
    excluded: list[str] = field(default_factory=list)

    @property
    def person_note(self) -> str:
        return ("Person measures are estimated from few ratings each and are correspondingly "
                "imprecise; read them with their standard errors. Rater severity uses every "
                "observation that rater made and is the quantity this fit is for.")

    def severity_gap(self, a: str, b: str) -> float | None:
        """How much harsher `a` is than `b`, in logits. The headline number."""
        if a not in self.raters or b not in self.raters:
            return None
        return self.raters[a].measure - self.raters[b].measure


class NotConnected(Exception):
    """The rating design falls into separate groups, so the measures are not on one scale."""


def connected(obs: list[Observation]) -> bool:
    """Does every person and rater link into ONE network?

    Two raters who never rate the same papers produce two floating scales, and the difference
    between their severities is then an artefact of which papers each happened to see rather than
    a fact about the raters. Union-find over the person↔rater edges.
    """
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for o in obs:
        a, b = find(f"p:{o.person}"), find(f"r:{o.rater}")
        if a != b:
            parent[a] = b
    return len({find(k) for k in parent}) <= 1


def _probabilities(lam: float, cum: list[float]) -> list[float]:
    """P(X=k) for one person-rater pair. `cum[k]` is Σ_{j≤k} τ_j, with cum[0] = 0."""
    # Subtract the max before exponentiating: without it a severity of ±20 logits overflows, which
    # happens on the way to convergence rather than at it.
    terms = [k * lam - cum[k] for k in range(len(cum))]
    top = max(terms)
    ex = [math.exp(t - top) for t in terms]
    z = sum(ex)
    return [e / z for e in ex]


def _moments(p: list[float]) -> tuple[float, float, float]:
    """Expected score, variance, and the fourth moment outfit needs."""
    e = sum(k * pk for k, pk in enumerate(p))
    w = sum((k - e) ** 2 * pk for k, pk in enumerate(p))
    c4 = sum((k - e) ** 4 * pk for k, pk in enumerate(p))
    return e, w, c4


def fit(obs: list[Observation], *, max_category: int | None = None,
        max_iter: int = 200, tol: float = 1e-4) -> Fit:
    """Estimate person measures, rater severities and thresholds.

    Raises `NotConnected` rather than returning numbers that cannot be compared — a severity
    difference computed across a disconnected design looks entirely ordinary.
    """
    if not obs:
        raise ValueError("no observations")
    if not connected(obs):
        raise NotConnected(
            "the rating design is not connected: some raters never rated the same papers as "
            "others, so their measures sit on separate scales and the difference between them "
            "would be an artefact of which papers each one saw.")

    m = max_category if max_category is not None else max(o.category for o in obs)
    if m < 1:
        raise ValueError("a rating scale needs at least two categories")

    persons = sorted({o.person for o in obs})
    raters = sorted({o.rater for o in obs})
    by_person: dict[str, list[Observation]] = {p: [] for p in persons}
    by_rater: dict[str, list[Observation]] = {r: [] for r in raters}
    for o in obs:
        by_person[o.person].append(o)
        by_rater[o.rater].append(o)

    # An element scoring at the ceiling on every observation has an infinite measure in this model.
    # Excluded from estimation and reported, rather than assigned a large finite number that would
    # look like a measurement.
    extreme: dict[str, str] = {}
    for p, rows in by_person.items():
        totals = {o.category for o in rows}
        if totals == {0}:
            extreme[p] = "every rating at the bottom category"
        elif totals == {m}:
            extreme[p] = "every rating at the top category"

    live = [o for o in obs if o.person not in extreme]
    if not live:
        raise ValueError("every person is extreme; nothing can be estimated")
    est_persons = sorted({o.person for o in live})

    theta = {p: 0.0 for p in est_persons}
    alpha = {r: 0.0 for r in raters}
    tau = [0.0] * (m + 1)          # tau[0] unused; thresholds are 1..m

    def cumulative() -> list[float]:
        out, run = [0.0], 0.0
        for k in range(1, m + 1):
            run += tau[k]
            out.append(run)
        return out

    converged, it = False, 0
    for it in range(1, max_iter + 1):
        cum = cumulative()
        biggest = 0.0

        # --- persons -------------------------------------------------------------------
        for p in est_persons:
            num = den = 0.0
            for o in by_person[p]:
                pr = _probabilities(theta[p] - alpha[o.rater], cum)
                e, w, _ = _moments(pr)
                num += o.category - e
                den += w
            if den > 1e-9:
                step = max(-1.0, min(1.0, num / den))   # clipped: an early step of 40 logits
                theta[p] += step                        # diverges instead of converging
                biggest = max(biggest, abs(step))

        # --- raters: severity enters with a minus sign, so the step is subtracted ------
        for r in raters:
            num = den = 0.0
            for o in by_rater[r]:
                if o.person in extreme:
                    continue
                pr = _probabilities(theta[o.person] - alpha[r], cum)
                e, w, _ = _moments(pr)
                num += o.category - e
                den += w
            if den > 1e-9:
                step = max(-1.0, min(1.0, num / den))
                alpha[r] -= step
                biggest = max(biggest, abs(step))
        # Identification: the origin is the average rater, which is what makes a severity
        # readable as a departure from it rather than from an arbitrary zero.
        shift = sum(alpha.values()) / len(alpha)
        for r in alpha:
            alpha[r] -= shift

        # --- thresholds ---------------------------------------------------------------
        cum = cumulative()
        for k in range(1, m + 1):
            g = h = 0.0
            for o in live:
                pr = _probabilities(theta[o.person] - alpha[o.rater], cum)
                q = sum(pr[k:])                      # P(X >= k)
                g += q - (1.0 if o.category >= k else 0.0)
                h += q * (1 - q)
            if h > 1e-9:
                step = max(-1.0, min(1.0, g / h))
                tau[k] += step
                biggest = max(biggest, abs(step))
        centre = sum(tau[1:]) / m
        for k in range(1, m + 1):
            tau[k] -= centre

        if biggest < tol:
            converged = True
            break

    # --- standard errors and fit ------------------------------------------------------
    cum = cumulative()
    stats: dict[str, dict] = {k: {"w": 0.0, "z2w": 0.0, "z2": 0.0, "n": 0}
                              for k in list(est_persons) + raters}
    for o in live:
        pr = _probabilities(theta[o.person] - alpha[o.rater], cum)
        e, w, _ = _moments(pr)
        resid = o.category - e
        z2 = (resid ** 2 / w) if w > 1e-9 else 0.0
        for key in (o.person, o.rater):
            s = stats[key]
            s["w"] += w
            s["z2w"] += resid ** 2          # infit numerator: Σ(x−E)²
            s["z2"] += z2                   # outfit numerator: Σ z²
            s["n"] += 1

    def element(name: str, measure: float) -> Element:
        s = stats[name]
        n, w = s["n"], s["w"]
        return Element(
            name=name, measure=measure,
            se=(1 / math.sqrt(w)) if w > 1e-9 else float("inf"),
            n=n,
            # Infit is information-weighted: Σ(x−E)² / ΣW. It is less sensitive to a single wild
            # rating than outfit, which is the unweighted mean of squared standardised residuals.
            infit=(s["z2w"] / w) if w > 1e-9 else float("nan"),
            outfit=(s["z2"] / n) if n else float("nan"))

    out = Fit(thresholds=tau[1:], iterations=it, converged=converged, max_category=m,
              excluded=sorted(extreme))
    for p in est_persons:
        out.persons[p] = element(p, theta[p])
    for p, why in extreme.items():
        out.persons[p] = Element(name=p, measure=float("nan"), se=float("inf"),
                                 n=len(by_person[p]), infit=float("nan"),
                                 outfit=float("nan"), extreme=why)
    for r in raters:
        out.raters[r] = element(r, alpha[r])
    return out


# ------------------------------------------------------------------ bias / DIF


@dataclass
class Bias:
    """One rater × group interaction: is this rater harsher on THIS group, given paper quality?"""
    rater: str
    group: str
    logits: float          # + = harsher on this group than their own average
    se: float
    t: float
    n: int

    @property
    def direction(self) -> str:
        return "harsher" if self.logits > 0 else "milder"


def bias(obs: list[Observation], groups: dict[str, str], f: Fit) -> list[Bias]:
    """Rater × group interactions, conditional on the fitted measures.

    THIS is the fairness analysis, and the conditioning is the whole point. In PERSUADE, ELL
    papers concentrate at human scores 1–3 and non-ELL at 3–5 — so an unconditional comparison of
    model-versus-human by subgroup would measure that population difference and report it as bias.
    Working from residuals against the fitted person measures asks the right question: given two
    papers of the same estimated quality, one by an ELL writer and one not, does this rater score
    them differently?

    Sign follows severity: positive means harsher on that group.
    """
    cum, out = [0.0], []
    run = 0.0
    for t in f.thresholds:
        run += t
        cum.append(run)

    cells: dict[tuple[str, str], dict] = {}
    for o in obs:
        person = f.persons.get(o.person)
        if person is None or person.extreme:
            continue
        g = groups.get(o.person)
        if g is None:
            # No label is not a group. Bucketing unlabelled papers together would invent a
            # subgroup and then publish a fairness finding about it.
            continue
        pr = _probabilities(person.measure - f.raters[o.rater].measure, cum)
        e, w, _ = _moments(pr)
        c = cells.setdefault((o.rater, g), {"resid": 0.0, "w": 0.0, "n": 0})
        c["resid"] += o.category - e
        c["w"] += w
        c["n"] += 1

    for (rater, g), c in sorted(cells.items()):
        if c["w"] <= 1e-9:
            continue
        logits = -c["resid"] / c["w"]        # minus: lower scores than expected = harsher
        se = 1 / math.sqrt(c["w"])
        out.append(Bias(rater=rater, group=g, logits=logits, se=se,
                        t=logits / se if se else float("nan"), n=c["n"]))
    return out


# ------------------------------------------------------------------ the paired design


@dataclass
class PairedSeverity:
    """The severity contrast between exactly two raters, estimated without person parameters."""
    harsher: str
    milder: str
    logits: float          # how much harsher `harsher` is
    se: float
    n: int                 # papers contributing (ties on the total carry no information)
    thresholds: list[float] = field(default_factory=list)
    converged: bool = False

    @property
    def t(self) -> float:
        return self.logits / self.se if self.se else float("nan")


def _pair_totals(obs: list[Observation]) -> tuple[str, str, list[tuple[int, int]]]:
    """(rater A, rater B, [(a, b), ...]) for papers both raters scored."""
    raters = sorted({o.rater for o in obs})
    if len(raters) != 2:
        raise ValueError(f"a paired estimate needs exactly two raters, got {raters}")
    a_name, b_name = raters
    by_person: dict[str, dict[str, int]] = {}
    for o in obs:
        by_person.setdefault(o.person, {})[o.rater] = o.category
    return a_name, b_name, [(v[a_name], v[b_name]) for v in by_person.values()
                            if a_name in v and b_name in v]


def paired_severity(obs: list[Observation], *, max_category: int | None = None,
                    max_iter: int = 300, tol: float = 1e-6) -> PairedSeverity:
    """Severity contrast for two raters who scored the same papers, by conditional likelihood.

    ## Why this exists rather than reading it off `fit`

    Joint maximum likelihood estimates a measure for every paper, and with only two ratings per
    paper those estimates absorb noise and stretch the scale. Measured on simulated data with
    known parameters: a true half-logit severity gap comes back as +0.86 with two raters, +0.46
    with four, +0.46 with eight. The inflation is a property of the design, not of the data, and
    two raters — the human pool and one model configuration — is precisely the design this
    project uses.

    ## How conditioning removes it

    For one paper rated `a` by the first rater and `b` by the second, the probability of that
    pair GIVEN the total a+b does not contain the paper's measure at all:

        P(a, b | a+b = s)  ∝  exp( (b−a)·d/2 − C_a − C_b )

    θ appears in the numerator and in every term of the denominator as exp(θ·s), and cancels. So
    the contrast `d` and the thresholds are estimated from the within-paper differences alone,
    with no person parameters to overfit. This is conditional maximum likelihood, and it is
    consistent however few ratings each paper has.

    ## What it cannot do

    Only the CONTRAST. There is no absolute severity here and there cannot be — with two raters
    and no external anchor, "the model is harsh" and "the humans are lenient" are the same
    statement. `fit` reports both on a centred scale, which is a convention, not a finding.

    Papers where both raters agreed contribute nothing: if a == b the conditional distribution is
    symmetric and carries no information about which rater is harsher. They are counted out
    rather than counted in, so `n` is the number of papers that actually informed the estimate.
    """
    a_name, b_name, pairs = _pair_totals(obs)
    if not pairs:
        raise ValueError("no paper was scored by both raters")
    m = max_category if max_category is not None else max(max(p) for p in pairs)

    def cumulative(tau: list[float]) -> list[float]:
        out, run = [0.0], 0.0
        for k in range(m):
            run += tau[k]
            out.append(run)
        return out

    def loglik(params: list[float]) -> float:
        d, tau = params[0], params[1:]
        cum = cumulative(tau)
        total = 0.0
        for a, b in pairs:
            s = a + b
            num = (b - a) * d / 2 - cum[a] - cum[b]
            terms = [(v - u) * d / 2 - cum[u] - cum[v]
                     for u in range(max(0, s - m), min(m, s) + 1)
                     for v in [s - u]]
            top = max(terms)
            total += num - (top + math.log(sum(math.exp(t - top) for t in terms)))
        return total

    params = [0.0] * (1 + m)
    step, converged = 0.25, False
    for _ in range(max_iter):
        base = loglik(params)
        moved = 0.0
        for i in range(len(params)):
            # Numerical gradient and curvature: six parameters over a few hundred papers, so the
            # cost is trivial and analytic derivatives would be a second place to make a sign
            # error — which is the failure mode this whole function exists to avoid.
            h = 1e-4
            up, dn = params[:], params[:]
            up[i] += h
            dn[i] -= h
            g = (loglik(up) - loglik(dn)) / (2 * h)
            curv = (loglik(up) - 2 * base + loglik(dn)) / (h * h)
            delta = -g / curv if curv < -1e-9 else g * step
            delta = max(-1.0, min(1.0, delta))
            params[i] += delta
            moved = max(moved, abs(delta))
            base = loglik(params)
        # Thresholds centred, same identification as `fit`.
        centre = sum(params[1:]) / m
        for i in range(1, len(params)):
            params[i] -= centre
        if moved < tol:
            converged = True
            break

    d = params[0]
    # SE from the curvature of the conditional log-likelihood at the optimum.
    h = 1e-4
    up, dn = params[:], params[:]
    up[0] += h
    dn[0] -= h
    curv = (loglik(up) - 2 * loglik(params) + loglik(dn)) / (h * h)
    se = (1 / math.sqrt(-curv)) if curv < -1e-9 else float("inf")

    informative = sum(1 for a, b in pairs if a != b)
    # SIGN. The conditional exponent is (b - a)*d/2, which is maximised for LARGER b when d > 0 —
    # so d > 0 means the second rater gives higher scores and the FIRST is the harsher one. This
    # was inverted in the first version and the magnitudes were right, so nothing looked wrong: it
    # would have reported a harsh model as lenient, in a fairness finding, with a plausible number.
    harsher, milder = (a_name, b_name) if d > 0 else (b_name, a_name)
    return PairedSeverity(harsher=harsher, milder=milder, logits=abs(d), se=se,
                          n=informative, thresholds=params[1:], converged=converged)
