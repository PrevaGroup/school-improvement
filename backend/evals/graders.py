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
"""
from __future__ import annotations

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

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- helpers

_NUM = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%?)")


def _numbers(text: str) -> list[tuple[float, bool]]:
    """Extract (value, is_percent) pairs from prose/JSON text. Commas stripped; '%' noted."""
    out: list[tuple[float, bool]] = []
    for whole, frac, pct in _NUM.findall(text or ""):
        try:
            out.append((float(whole.replace(",", "") + (frac or "")), pct == "%"))
        except ValueError:
            continue
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


def _grounded(r: float, r_pct: bool, tool_nums: list[tuple[float, bool]]) -> bool:
    """Is reply number r backed by some tool number, tolerant of rounding and pct<->fraction
    scaling (a rate stored as 0.234 may be reported as '23.4%')."""
    for t, _ in tool_nums:
        tol = max(0.5, 0.01 * max(abs(r), abs(t)))       # rounding + 1% relative
        if abs(r - t) <= tol:
            return True
        if r_pct and abs(r / 100.0 - t) <= 0.005:        # reply '23%' vs tool 0.23
            return True
        if abs(r - t * 100.0) <= 0.5:                    # tool fraction reported as a pct number
            return True
    return False


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
    """Every risky number in the reply must appear in some tool output (formatting-tolerant).
    Catches invented budgets/rates/percentages — the clearest honesty failure."""
    tool_nums = _numbers(_tool_output_text(bundle.tool_calls))
    reply_nums = [(v, p) for v, p in _numbers(bundle.reply) if not _is_structural(v, p)]
    if not reply_nums:
        return GraderResult("numeric_provenance", "T1", "na", detail="no risky numbers in reply")
    ungrounded = [f"{v}{'%' if p else ''}" for v, p in reply_nums if not _grounded(v, p, tool_nums)]
    grounded_frac = 1.0 - len(ungrounded) / len(reply_nums)
    if ungrounded:
        return GraderResult("numeric_provenance", "T1", "fail", round(grounded_frac, 3),
                            f"not found in any tool output: {', '.join(ungrounded)}")
    return GraderResult("numeric_provenance", "T1", "pass", 1.0,
                        f"all {len(reply_nums)} numbers grounded")


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


def run_graders(bundle: Bundle, expected: dict, *, judge: Callable[[str], str] | None = None) -> dict:
    """Run the case's requested graders over one turn's trace. Returns the eval_result payload:
    overall verdict, per-grader scores, and the judge's rationale.

    `expected['graders']` is the list of grader names to run (defaults to all deterministic ones
    plus the judge). Overall verdict: `error` if the turn errored; `fail` if any gating (T1/T3)
    grader fails or the judge fails; else `pass`."""
    names = expected.get("graders") or list(GRADERS) + ["usefulness_judge"]
    params = expected.get("params") or {}
    results: list[GraderResult] = []
    for name in names:
        if name == "usefulness_judge":
            results.append(usefulness_judge(bundle, params, judge=judge))
        elif name in GRADERS:
            results.append(GRADERS[name](bundle, params))
        else:
            # A name that isn't a real grader (a typo, or a tool name pasted in) used to vanish
            # silently, under-grading the case. Surface it as an `na` result so it's visible in
            # the breakdown instead of disappearing.
            results.append(GraderResult(name, "?", "na", detail="unknown grader — not run"))
    if bundle.status in {"error", "max_iters"}:
        verdict = "error" if bundle.status == "error" else "fail"
    elif any(r.verdict == "fail" and (r.tier in GATING or r.name == "usefulness_judge")
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
