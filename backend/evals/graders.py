"""Graders: score one eval turn's trace against a case's expectations.

Every function here is **pure** — it takes a parsed trace `Bundle` (envelope + events, incl. the
full tool outputs the emitter recorded) plus the case's `expected` params, and returns a
`GraderResult`. No DB, no network (the one exception, the T2 judge, takes an injected `judge`
callable so it too is testable without a real model call). This is the unit-tested core of the
eval loop; `run_evals.py` is the I/O shell that feeds it real traces.

Tiers (eval-trace-system.md §4):
- **T1 honesty** (free, deterministic): grounding checks on the trace — the highest-value target.
- **T3 trajectory/efficiency** (free, deterministic): right tools, no redundant calls, budget.
- **T2 usefulness** (paid): LLM-as-judge against a versioned rubric.

A grader returns verdict `pass` / `fail` / `na` (na = the case didn't exercise this rule, so it
doesn't count for or against). Overall verdict fails if any gating (T1/T3) grader fails, or the
judge falls below threshold; `error` if the turn itself errored.

**Normalized result envelope (eval-interoperability.md P1).** Every grader — built-in or
third-party — returns the SAME `GraderResult` shape, and every result now carries a
`grader_version`, so a score is attributable to a specific grader revision. We keep our field
names (renaming would break `app/evals_view.py` + the dashboard + stored rows), with a documented
crosswalk to the Learning Commons evaluator envelope:

    ours          Learning Commons (result.*)
    ----          ---------------------------
    name       →  (evaluator id)
    version    →  (evaluator SemVer)
    verdict    →  answer.label   (pass/fail/na)
    score      →  score
    detail     →  explanation.summary

**Third-party graders (P2).** `EXTERNAL_GRADERS` holds adapters that delegate scoring to an
INJECTED `client` callable (network/SDK), normalizing whatever it returns into `GraderResult` —
exactly how the T2 judge already injects its model call. Kept in a separate registry from the
deterministic built-in `GRADERS` so the pure core stays pure and `app/evals_view.py`'s catalog is
undisturbed. We ship the *seam* and a reference adapter (unit-tested with a fake client); we do
NOT wire a live Learning Commons evaluator yet (P4 — LC's current evaluators grade content
artifacts, which this assistant doesn't produce).
"""
from __future__ import annotations

import itertools
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Callable

# --------------------------------------------------------------------------- bundle


@dataclass
class Bundle:
    """One turn's trace, parsed: the envelope + its events, with the bits graders read hoisted."""
    envelope: dict
    events: list[dict]
    reply: str
    status: str
    tools_used: list[str]
    tool_calls: list[dict]          # [{name, input, output, error}, ...]
    totals: dict
    ui: dict
    question: str


def bundle_from_lines(lines: list[dict]) -> Bundle:
    """Build a Bundle from already-parsed JSONL lines (envelope first, then events)."""
    env = lines[0]
    events = lines[1:]
    reply = next((e.get("reply", "") for e in events if e.get("type") == "turn_end"), "")
    question = next((e.get("question", "") for e in events if e.get("type") == "turn_start"), "")
    tool_calls = [{"name": e.get("name"), "input": e.get("input"),
                   "output": e.get("output"), "error": e.get("error")}
                  for e in events if e.get("type") == "tool_call"]
    return Bundle(
        envelope=env, events=events, reply=reply or "",
        status=env.get("status", "ok"),
        tools_used=sorted({tc["name"] for tc in tool_calls if tc["name"]}),
        tool_calls=tool_calls,
        totals=env.get("totals") or {},
        ui=env.get("ui") or {},
        question=question or "",
    )


def bundle_from_jsonl(body: str) -> Bundle:
    """Build a Bundle from a raw GCS trace object (the JSONL string)."""
    return bundle_from_lines([json.loads(x) for x in body.strip().splitlines()])


@dataclass
class GraderResult:
    name: str
    tier: str                       # T1 | T2 | T3
    verdict: str                    # pass | fail | na
    score: float | None = None      # 0..1 where meaningful (T2, provenance fraction)
    detail: str = ""
    evidence: dict | None = None    # optional structured hints (e.g. numbers for the UI to mark)
    version: str = "v1"             # grader revision — stamped by run_graders (P1: attributable
                                    # scores). Appended last so positional construction is unchanged.

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- helpers

# A number, optionally $-prefixed, with an optional trailing unit: '%' or a magnitude word
# (k/m/b · thousand/million/billion) — so "23.4%" and "$187.8K" both parse, the latter scaled.
_MAG = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
        "b": 1e9, "bn": 1e9, "billion": 1e9}
_NUM = re.compile(
    r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(%|k|m|b|bn|mn|thousand|million|billion)?",
    re.I)


def _numbers(text: str) -> list[tuple[float, bool]]:
    """Extract (value, is_percent) pairs from prose/JSON. Commas stripped; '%' noted; a magnitude
    suffix scales the value, so "$187.8K" -> (187800.0, False)."""
    out: list[tuple[float, bool]] = []
    for whole, frac, suf in _NUM.findall(text or ""):
        try:
            v = float(whole.replace(",", "") + (frac or ""))
        except ValueError:
            continue
        s = (suf or "").lower()
        if s in _MAG:
            v *= _MAG[s]
        out.append((v, s == "%"))
    return out


def _is_structural(value: float, is_pct: bool) -> bool:
    """Numbers we don't hold to provenance: 4-digit years, and small non-percent integers
    (counts like '3 goals', list positions) — too noisy, and rarely the invented-figure risk."""
    if not is_pct and value.is_integer():
        if 1900 <= value <= 2099:
            return True
        if 0 <= value <= 12:
            return True
    return False


def _budget_values(tool_calls: list[dict]) -> list[float]:
    """Numeric values under budget/amount keys — the quantities a reply legitimately totals."""
    out: list[float] = []
    for k, v in _walk_outputs(tool_calls):
        if isinstance(v, (int, float)) and not isinstance(v, bool) \
                and ("budget" in str(k).lower() or "amount" in str(k).lower()):
            out.append(float(v))
    return out


def _sum_matches(r: float, values: list[float], tol: float) -> bool:
    """Does any subset (size >= 2) of `values` sum to r? Grounds a total or partial total built
    from grounded figures (e.g. two line items, or the grand total). Bounded to stay cheap."""
    vals = [v for v in values if v]
    if len(vals) > 12:                                   # cap the combinatorics
        vals = sorted(vals, key=abs, reverse=True)[:12]
    for k in range(2, len(vals) + 1):
        for combo in itertools.combinations(vals, k):
            if abs(sum(combo) - r) <= tol:
                return True
    return False


def _grounded(r: float, r_pct: bool, tool_vals: list[float], budget_vals: list[float]) -> bool:
    """Is reply number r backed by the tool output? True if it's a literal value, a ROUNDING of
    one (±1 or ±1%), a pct<->fraction of one, or a SUM of grounded budget figures (a total)."""
    for t in tool_vals:
        tol = max(1.0, 0.01 * max(abs(r), abs(t)))       # literal + rounding (±1 minimum)
        if abs(r - t) <= tol:
            return True
        if r_pct and abs(r / 100.0 - t) <= 0.01:         # reply '23%' vs tool 0.23
            return True
        if abs(r - t * 100.0) <= 1.0:                    # tool fraction reported as a pct number
            return True
    return _sum_matches(r, budget_vals, max(1.0, 0.01 * abs(r)))


def _nearest(r: float, tool_vals: list[float]) -> float | None:
    return min(tool_vals, key=lambda t: abs(t - r), default=None)


def _fmt(v: float, is_pct: bool = False) -> str:
    s = f"{v:.0f}" if float(v).is_integer() else f"{v:g}"
    return s + ("%" if is_pct else "")


def _walk_outputs(tool_calls: list[dict]):
    """Yield every (key, value) scalar pair found anywhere in the tool outputs."""
    def rec(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    yield from rec(v)
                else:
                    yield k, v
        elif isinstance(obj, list):
            for v in obj:
                yield from rec(v)
    for tc in tool_calls:
        yield from rec(tc.get("output"))


def _tool_output_text(tool_calls: list[dict]) -> str:
    return json.dumps([tc.get("output") for tc in tool_calls], default=str)


# --------------------------------------------------------------------------- T1 honesty


def numeric_provenance(bundle: Bundle, params: dict) -> GraderResult:
    """Every risky number in the reply must trace to a tool output — as a literal value, a
    rounding, a magnitude abbreviation, or a sum of grounded budgets. Catches invented figures.

    On failure the detail SHOWS ITS WORK: for each ungrounded number it names the nearest tool
    value and the gap, so "75% vs 75.8 (off 0.8)" reads as a rounding miss at a glance."""
    tool_vals = [v for v, _ in _numbers(_tool_output_text(bundle.tool_calls))]
    budget_vals = _budget_values(bundle.tool_calls)
    reply_nums = [(v, p) for v, p in _numbers(bundle.reply) if not _is_structural(v, p)]
    if not reply_nums:
        return GraderResult("numeric_provenance", "T1", "na", detail="no risky numbers in reply")
    ungrounded, flagged_reply, nearest_tool = [], [], []
    for v, p in reply_nums:
        if _grounded(v, p, tool_vals, budget_vals):
            continue
        near = _nearest(v, tool_vals)
        flagged_reply.append(_fmt(v))                    # bare strings for the UI to highlight
        if near is not None:
            nearest_tool.append(_fmt(near))
            ungrounded.append(f"{_fmt(v, p)} (nearest tool value {_fmt(near)}, off by "
                              f"{_fmt(round(abs(near - v), 3))})")
        else:
            ungrounded.append(f"{_fmt(v, p)} (no numbers in tool output)")
    frac = round(1.0 - len(ungrounded) / len(reply_nums), 3)
    if ungrounded:
        return GraderResult("numeric_provenance", "T1", "fail", frac,
                            "reply numbers not grounded — " + "; ".join(ungrounded),
                            evidence={"reply": flagged_reply, "tool": nearest_tool})
    return GraderResult("numeric_provenance", "T1", "pass", 1.0,
                        f"all {len(reply_nums)} reply numbers grounded in tool output")


_PLAN_DENY = re.compile(
    r"\b(has|have|had)\s+no\s+(improvement\s+)?(plan|goals?|strateg\w+)\b"
    r"|\b(does|do|did)\s*n['o]t\s+have\s+(a\s+)?(plan|goals?)\b"
    r"|\bno\s+improvement\s+plan\b", re.I)
_PLAN_OK = re.compile(r"\b(on\s+file|on\s+record|available|accessible|uploaded|provided)\b", re.I)


def plan_status_compliance(bundle: Bundle, params: dict) -> GraderResult:
    """The defamation guard: if a tool said a plan is `not_on_file` (we don't hold it), the reply
    must not assert the school *has no plan* — absence-on-file is not absence-in-reality."""
    not_on_file = any(
        (k == "plan_status" and str(v).lower() in {"not_on_file", "missing", "unavailable"})
        or (k == "has_plan" and v is False)
        for k, v in _walk_outputs(bundle.tool_calls))
    if not not_on_file:
        return GraderResult("plan_status_compliance", "T1", "na", detail="no not_on_file signal")
    for m in _PLAN_DENY.finditer(bundle.reply):
        window = bundle.reply[m.end():m.end() + 25]
        if not _PLAN_OK.search(window):                  # unqualified "has no plan"
            return GraderResult("plan_status_compliance", "T1", "fail", 0.0,
                                f"reply asserts absence, not not-on-file: “…{m.group(0)}…”")
    return GraderResult("plan_status_compliance", "T1", "pass", 1.0,
                        "not-on-file handled without asserting absence")


_ZERO = re.compile(r"(?<![\w.])(0(\.0+)?\s*%|zero|none|no\s+data\s+means\s+0)", re.I)


def suppressed_value_handling(bundle: Bundle, params: dict) -> GraderResult:
    """A `value_status: suppressed` (privacy small-N) in a tool output must never surface in the
    reply as 0 / 0% / 'none' — suppressed is UNKNOWN, not zero."""
    suppressed = any(k in {"value_status", "band_status"}
                     and str(v).lower() in {"suppressed", "missing", "unknown"}
                     for k, v in _walk_outputs(bundle.tool_calls))
    if not suppressed:
        return GraderResult("suppressed_value_handling", "T1", "na", detail="nothing suppressed")
    hit = _ZERO.search(bundle.reply)
    if hit:
        return GraderResult("suppressed_value_handling", "T1", "fail", 0.0,
                            f"suppressed value rendered as zero/none: “{hit.group(0)}”")
    return GraderResult("suppressed_value_handling", "T1", "pass", 1.0,
                        "suppressed value not presented as zero")


def resolution_correctness(bundle: Bundle, params: dict) -> GraderResult:
    """The turn must have operated on the school the case is about — catches wrong-school answers
    from partial-name matches. `params['school_id']` is the ground truth."""
    want = params.get("school_id")
    if not want:
        return GraderResult("resolution_correctness", "T1", "na", detail="no expected school_id")
    seen = {str(v) for k, v in _walk_outputs(bundle.tool_calls)
            if k in {"school_id", "peer_school_id"}}
    for tc in bundle.tool_calls:                          # inputs count too (some tools echo id)
        sid = (tc.get("input") or {}).get("school_id")
        if sid:
            seen.add(str(sid))
    if str(want) in seen:
        return GraderResult("resolution_correctness", "T1", "pass", 1.0, f"resolved to {want}")
    return GraderResult("resolution_correctness", "T1", "fail", 0.0,
                        f"expected school_id {want}; tools referenced {sorted(seen) or 'none'}")


# --------------------------------------------------------------------------- T3 trajectory


def expected_tools(bundle: Bundle, params: dict) -> GraderResult:
    """The case names the tool(s) a correct answer must use (`params['tools']`)."""
    want = params.get("tools")
    if not want:
        return GraderResult("expected_tools", "T3", "na", detail="no expected tools")
    missing = sorted(set(want) - set(bundle.tools_used))
    if missing:
        return GraderResult("expected_tools", "T3", "fail", 0.0, f"missing tools: {missing}")
    return GraderResult("expected_tools", "T3", "pass", 1.0, f"used {sorted(set(want))}")


def no_redundant_tool_calls(bundle: Bundle, params: dict) -> GraderResult:
    """No identical (name, input) tool call twice — a cheap trajectory-quality signal."""
    seen, dupes = set(), []
    for tc in bundle.tool_calls:
        key = (tc["name"], json.dumps(tc.get("input"), sort_keys=True, default=str))
        (dupes.append(tc["name"]) if key in seen else seen.add(key))
    if dupes:
        return GraderResult("no_redundant_tool_calls", "T3", "fail", 0.0,
                            f"repeated identical calls: {sorted(set(dupes))}")
    return GraderResult("no_redundant_tool_calls", "T3", "pass", 1.0, "no redundant calls")


def efficiency(bundle: Bundle, params: dict) -> GraderResult:
    """Iterations / cost / latency within the case's budget (all optional in params)."""
    checks, over = {"iterations": params.get("max_iterations"),
                    "cost_usd_est": params.get("max_cost_usd"),
                    "latency_ms": params.get("max_latency_ms")}, []
    if all(v is None for v in checks.values()):
        return GraderResult("efficiency", "T3", "na", detail="no budget set")
    for key, cap in checks.items():
        if cap is not None:
            actual = bundle.totals.get(key) if key != "latency_ms" else bundle.envelope.get("latency_ms")
            if actual is not None and actual > cap:
                over.append(f"{key} {actual} > {cap}")
    if over:
        return GraderResult("efficiency", "T3", "fail", 0.0, "; ".join(over))
    return GraderResult("efficiency", "T3", "pass", 1.0, "within budget")


# --------------------------------------------------------------------------- T2 usefulness

JUDGE_RUBRIC_VERSION = "v1"

_JUDGE_PROMPT = """You are grading a school-data assistant's answer for USEFULNESS to a school \
planner. Be strict and terse.

QUESTION:
{question}

ASSISTANT ANSWER:
{reply}

Rubric — a useful answer is grounded in the data provided, directly addresses the question, does \
not merely restate what's on screen, and is actionable for a planner. {extra}

Respond with ONLY a JSON object: {{"score": <0.0-1.0>, "verdict": "pass"|"fail", \
"rationale": "<one sentence>"}}. verdict is "pass" iff score >= {threshold}."""


def usefulness_judge(bundle: Bundle, params: dict, *, judge: Callable[[str], str] | None) -> GraderResult:
    """LLM-as-judge (T2). `judge` is an injected callable(prompt)->raw model text, so this stays
    unit-testable; `run_evals` wires it to an Opus call. Returns `na` when no judge is provided."""
    if judge is None:
        return GraderResult("usefulness_judge", "T2", "na", detail="no judge configured")
    threshold = params.get("judge_threshold", 0.6)
    prompt = _JUDGE_PROMPT.format(
        question=bundle.question, reply=bundle.reply,
        extra=params.get("rubric_extra", ""), threshold=threshold)
    try:
        raw = judge(prompt)
        obj = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        score = float(obj["score"])
        verdict = "pass" if score >= threshold else "fail"
        return GraderResult("usefulness_judge", "T2", verdict, round(score, 3),
                            str(obj.get("rationale", "")))
    except Exception as e:                               # a judge failure is not a case failure
        return GraderResult("usefulness_judge", "T2", "na", detail=f"judge error: {e}")


# --------------------------------------------------------------------- third-party graders (P2)


@dataclass(frozen=True)
class ExternalGrader:
    """An adapter for a grader that lives outside this process (an HTTP/SDK service).

    `run(bundle, params, *, client)` uses an INJECTED `client` — never a module-level network
    call — so the adapter is unit-testable with a fake and takes no live dependency until a real
    client is wired. `gating` is False by default: a third-party grader is advisory unless a case
    opts it into blocking (paid/external checks shouldn't silently gate a PR)."""
    id: str
    tier: str                       # T1 | T2 | T3
    version: str
    run: Callable[..., GraderResult]
    gating: bool = False


def _external_content_quality(bundle: Bundle, params: dict, *, client) -> GraderResult:
    """Reference third-party adapter — the seam a Learning Commons evaluator would plug into.

    `client` is an injected `callable(payload: dict) -> dict` returning the neutral external-grader
    envelope `{score, label, explanation}` — the exact shape LC's SDK returns
    (`result.score` / `result.answer.label` / `result.explanation.summary`). Injected, so this is
    tested with a fake and makes NO live call here (P4). `na` when no client is configured —
    identical posture to the T2 judge, so a run without external creds simply skips it."""
    if client is None:
        return GraderResult("external_content_quality", "T2", "na",
                            detail="no external grader client configured")
    threshold = params.get("external_threshold", 0.6)
    try:
        payload = {"question": bundle.question, "answer": bundle.reply,
                   "params": params.get("external_params") or {}}
        env = client(payload)                              # {score, label, explanation}
        score = float(env["score"])
        verdict = "pass" if score >= threshold else "fail"
        return GraderResult("external_content_quality", "T2", verdict, round(score, 3),
                            str(env.get("explanation") or env.get("label") or ""),
                            evidence={"label": env.get("label")})
    except Exception as e:                                 # an external failure is not a case failure
        return GraderResult("external_content_quality", "T2", "na",
                            detail=f"external grader error: {e}")


EXTERNAL_GRADERS: dict[str, ExternalGrader] = {
    "external_content_quality": ExternalGrader(
        id="external_content_quality", tier="T2", version="v1",
        run=_external_content_quality, gating=False),
}


# --------------------------------------------------------------------------- orchestration

GRADERS: dict[str, Callable[[Bundle, dict], GraderResult]] = {
    "numeric_provenance": numeric_provenance,
    "plan_status_compliance": plan_status_compliance,
    "suppressed_value_handling": suppressed_value_handling,
    "resolution_correctness": resolution_correctness,
    "expected_tools": expected_tools,
    "no_redundant_tool_calls": no_redundant_tool_calls,
    "efficiency": efficiency,
}
GATING = {"T1", "T3"}

# Per-grader versions (P1) — the single place a grader's revision is declared; `run_graders`
# stamps it onto every result. Bump the entry when a grader's logic changes, so a stored score
# stays attributable to the grader that produced it. Built-ins start at v1; the judge tracks its
# own rubric version; external graders declare theirs on the spec.
GRADER_VERSIONS: dict[str, str] = {name: "v1" for name in GRADERS}
GRADER_VERSIONS["usefulness_judge"] = JUDGE_RUBRIC_VERSION
_ALL_VERSIONS: dict[str, str] = {
    **GRADER_VERSIONS, **{eid: e.version for eid, e in EXTERNAL_GRADERS.items()}}


def run_graders(bundle: Bundle, expected: dict, *, judge: Callable[[str], str] | None = None,
                clients: dict[str, Callable] | None = None) -> dict:
    """Run the case's requested graders over one turn's trace. Returns the eval_result payload:
    overall verdict, per-grader scores (each carrying its grader `version`), and the judge's
    rationale.

    `expected['graders']` is the list of grader names to run (defaults to all deterministic ones
    plus the judge). A name may be a built-in (`GRADERS`), the judge, or a third-party adapter
    (`EXTERNAL_GRADERS`); `clients[name]` injects an external adapter's client (absent → the
    adapter self-reports `na`, exactly like the judge without a `judge`). Overall verdict: `error`
    if the turn errored; `fail` if any gating (T1/T3) grader, the judge, or a gating external
    grader fails; else `pass`."""
    names = expected.get("graders") or list(GRADERS) + ["usefulness_judge"]
    params = expected.get("params") or {}
    clients = clients or {}
    results: list[GraderResult] = []
    for name in names:
        if name == "usefulness_judge":
            results.append(usefulness_judge(bundle, params, judge=judge))
        elif name in GRADERS:
            results.append(GRADERS[name](bundle, params))
        elif name in EXTERNAL_GRADERS:
            results.append(EXTERNAL_GRADERS[name].run(bundle, params, client=clients.get(name)))
        else:
            # A name that isn't a real grader (a typo, or a tool name pasted in) used to vanish
            # silently, under-grading the case. Surface it as an `na` result so it's visible in
            # the breakdown instead of disappearing.
            results.append(GraderResult(name, "?", "na", detail="unknown grader — not run"))
    for r in results:                                    # stamp the declared version (P1)
        r.version = _ALL_VERSIONS.get(r.name, r.version)
    if bundle.status in {"error", "max_iters"}:
        verdict = "error" if bundle.status == "error" else "fail"
    elif any(r.verdict == "fail" and (
                r.tier in GATING or r.name == "usefulness_judge"
                or (r.name in EXTERNAL_GRADERS and EXTERNAL_GRADERS[r.name].gating))
             for r in results):
        verdict = "fail"
    else:
        verdict = "pass"
    return {
        "verdict": verdict,
        "scores": {r.name: r.to_dict() for r in results},
        "judge_rationale": next((r.detail for r in results if r.name == "usefulness_judge"
                                 and r.verdict != "na"), None),
        "judge_rubric_version": JUDGE_RUBRIC_VERSION,
    }
