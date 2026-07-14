"""PDF -> reviewable-JSON extractor for California school-improvement plans.

Drives Claude over a SPSA / LCAP / CSI PDF and emits the staging JSON described by
`schema.py` (`ExtractedPlan`). The model reads the PDF natively (a base64 document
block, no OCR), extracts goals / actions / metric-link proposals with verbatim
page-level provenance, and returns a structured payload; this module then stamps the
deterministic IDs and source metadata that the model must NOT invent, validates the
whole thing against `schema.py`, and writes it to disk.

    raw/ca/districts/<LEAID>/sip/*.pdf  ->  extract_sip.py  ->  <plan>.json  ->  augment loader

Why a separate request-side schema (`PlanExtraction`): the deterministic `*_id`
fields and `SourceRef` in `schema.py` are computed from the bytes and the identity
crosswalk, not read from the page. Asking the model to build them invites drift, so
the model fills only what it can see and we assemble the canonical `ExtractedPlan`.

Run it the same way as the loaders — as a module from `backend/`, with ADC set
(`gcloud auth application-default login`) so the Anthropic key resolves from Secret
Manager (or set ANTHROPIC_API_KEY for a dev fallback):

    python -m etl.ca.sip.extract_sip <pdf|gs://...> [--out <json>] \
        [--district-id <NCES 7-digit>] [--school-id <NCES 12-digit>] \
        [--plan-year 2024-25] [--gs-uri gs://...] [--dry-run]

The source may be a local path or a gs:// URI (read via gcsfs/ADC). Point it straight
at the canonical raw path, e.g. gs://<bucket>/raw/ca/districts/<LEAID>/sip/<school>.pdf.

`--dry-run` does everything except the billed API call (reads the PDF, hashes it,
counts pages, builds the request) — use it to check plumbing without spending tokens.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import pathlib
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.append(str(pathlib.Path(__file__).resolve().parents[3]))  # -> backend/

from pydantic import BaseModel, Field

from app.config import settings
from .._shared import METRICS as _METRICS, STUDENT_GROUPS as _STUDENT_GROUPS
from .schema import (
    Direction,  # noqa: F401  (re-exported for prompt authors / typing parity)
    ExtractedAction,
    ExtractedGoal,
    ExtractedPlan,
    MetricLinkProposal,
    PlanType,
    Provenance,
    SourceRef,
    build_action_id,
    build_goal_id,
    build_plan_id,
)

MODEL_ID = "claude-opus-4-8"

# Conformed vocabulary is the single source of truth in `_shared.py` (what the CA
# loaders actually write to star.fact_metric / dim_student_group). Deriving the id
# lists here keeps the extractor's prompt in lockstep with the DB — a plan measure
# maps onto a real `dim_metric.metric_id` / `dim_student_group.student_group_id`, or
# the model proposes null when we don't yet conform it.
CONFORMED_METRIC_IDS = [m["metric_id"] for m in _METRICS]
CONFORMED_GROUP_IDS = [g[0] for g in _STUDENT_GROUPS]


# --------------------------------------------------------------------------- #
# Request-side schema — what the MODEL fills. Deterministic ids and SourceRef
# are stamped by us afterwards, so they are absent here on purpose.
# --------------------------------------------------------------------------- #
class ActionExtraction(BaseModel):
    action_number: Optional[str] = Field(None, description="label as printed, e.g. '1.2'")
    strategy_text: str = Field(..., description="what the school/district will do")
    category_id: Optional[str] = Field(None, description="instruction | pd | staffing | sel | family_engagement | materials | technology | other")
    budgeted_amount: Optional[float] = None
    funding_source_raw: Optional[str] = Field(None, description="funding source verbatim, e.g. 'LCFF Supplemental'")
    funding_source_id: Optional[str] = Field(None, description="mapped funding source id if obvious, else null")
    fte: Optional[float] = None
    role_type: Optional[str] = None
    is_district_provided: Optional[bool] = None
    metric_links: list[MetricLinkProposal] = Field(default_factory=list)
    provenance: Provenance


class GoalExtraction(BaseModel):
    goal_number: Optional[str] = Field(None, description="label as printed, e.g. '1'")
    goal_type: Optional[str] = Field(
        None,
        description="short snake_case label for the goal's role in the plan structure "
        "(district-specific, free text), e.g. strategic_5yr | subject | accountability_measure",
    )
    statement: str = Field(..., description="the goal statement / narrative")
    lcff_priority: Optional[int] = Field(None, description="LCFF state priority 1-8 (LCAP only), else null")
    target_group_id: Optional[str] = Field(None, description="conformed group_id or null")
    metric_links: list[MetricLinkProposal] = Field(default_factory=list, description="goal-level measures/targets")
    actions: list[ActionExtraction] = Field(default_factory=list)
    provenance: Provenance


class PlanExtraction(BaseModel):
    """Root payload the model returns for one PDF (identity + content, no ids)."""
    school_id: Optional[str] = Field(None, description="NCES 12-digit ncessch ONLY if printed in the PDF, else null")
    state_school_id: Optional[str] = Field(None, description="CA 14-digit CDS school code if printed, else null")
    state_district_id: Optional[str] = Field(None, description="CA 7-digit CDS district code if printed, else null")
    plan_type: PlanType
    plan_year: str = Field(..., description="school-year label, e.g. '2024-25'")
    status: Optional[str] = None
    adopted_date: Optional[date] = None
    total_budget: Optional[float] = None
    goals: list[GoalExtraction] = Field(default_factory=list)
    unresolved: list[str] = Field(
        default_factory=list,
        description="things seen but not confidently placed — never silently dropped",
    )


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #
def build_instruction(plan_year_hint: Optional[str], context: Optional[str] = None) -> str:
    metrics = ", ".join(CONFORMED_METRIC_IDS)
    groups = ", ".join(CONFORMED_GROUP_IDS)
    year_line = (
        f"The plan year is {plan_year_hint} unless the document clearly states otherwise."
        if plan_year_hint
        else "Read the plan year from the document."
    )
    context_block = (
        f"\nDistrict/format context (authoritative for structure and goal_type labels):\n{context}\n"
        if context
        else ""
    )
    return f"""You are extracting a California school-improvement plan (SPSA / LCAP / CSI / TSI / ATSI) from the attached PDF into structured JSON for human review.

Rules:
- Extract every goal, and under each goal every action/strategy. Do not summarize or merge.
- Classify each goal with a short snake_case `goal_type` naming its role in this plan's structure. This varies by district — if the context below defines the district's scheme, use those labels. Common California SPSA layers: strategic_5yr (multi-year board targets), subject (current-year ELA/Math/EL/climate goals), accountability_measure (numbered budget/intervention measures).
- For EVERY extracted fact (each goal, action, and metric link), fill `provenance` with the 1-based `page` and a VERBATIM `quote` copied from that page — no paraphrase. Set `confidence` in [0,1].
- {year_line} Use the compact 'YYYY-YY' format (e.g. '2025-26').
- For measurable targets (baselines, targets, "increase X from A% to B%"), create a `metric_links` entry:
  - `raw_metric_text`: the metric exactly as written in the plan.
  - `proposed_metric_id`: map to ONE of these conformed ids when it clearly matches, else null: {metrics}.
  - `target_group_id`: map to ONE of these conformed group ids when named, else null: {groups}.
  - `direction`: "increase" or "decrease" (the desired movement), or null.
  - Fill baseline_value/baseline_year/target_value/target_year when the plan states numbers; else null.
  - Always set `link_status` to "proposed".
- Identity (IMPORTANT): the SPSA title/cover page names the school and lists the 14-digit County-District-School (CDS) code — read them. Put the CDS in `state_school_id` and its 7-digit prefix in `state_district_id`. Fill `school_id` (NCES) only if an NCES id is actually printed. Never guess a code; if truly absent, null.
- If the plan states an approval/adoption date (e.g. "approved ... on 11/17/2025"), set `adopted_date` (YYYY-MM-DD) and keep `status` to a short label, not the whole sentence.
- Anything you see but cannot confidently place goes in `unresolved` as a short note.
{context_block}
Return only the structured object."""


# --------------------------------------------------------------------------- #
# Assembly — stamp deterministic ids + source, producing the canonical schema
# --------------------------------------------------------------------------- #
def _scope_school_id(px: PlanExtraction, school_id_nces: Optional[str]) -> Optional[str]:
    """Best available school-level identity for a stable, school-specific plan_id.

    Prefer a real NCES school id (CLI-supplied crosswalk), then the CDS code the
    model read off the page. None => the plan_id falls back to district scope,
    which is only correct for a genuinely district-level LCAP.
    """
    return school_id_nces or px.school_id or px.state_school_id


def assemble_plan(
    px: PlanExtraction,
    *,
    district_id: str,
    school_id_nces: Optional[str],
    gs_uri: str,
    sha256: str,
    page_count: int,
    extracted_at: str,
) -> ExtractedPlan:
    school_scope = _scope_school_id(px, school_id_nces)
    plan_year = _normalize_year(px.plan_year)
    plan_id = build_plan_id(district_id, school_scope, px.plan_type.value, plan_year)

    goals: list[ExtractedGoal] = []
    for gi, g in enumerate(px.goals, start=1):
        goal_number = g.goal_number or str(gi)
        # Key on the global sequence, NOT goal_number: a plan can restart numbering per
        # layer (strategic 1-4 AND accountability 1-4), so goal_number is not unique
        # within a plan and would collide on load. goal_number stays as the printed label.
        goal_id = build_goal_id(plan_id, f"n{gi}")
        actions: list[ExtractedAction] = []
        for ai, a in enumerate(g.actions, start=1):
            action_number = a.action_number or f"{goal_number}.{ai}"
            actions.append(
                ExtractedAction(
                    action_id=build_action_id(goal_id, action_number),
                    action_number=action_number,
                    strategy_text=a.strategy_text,
                    category_id=a.category_id,
                    budgeted_amount=a.budgeted_amount,
                    funding_source_raw=a.funding_source_raw,
                    funding_source_id=a.funding_source_id,
                    fte=a.fte,
                    role_type=a.role_type,
                    is_district_provided=a.is_district_provided,
                    metric_links=a.metric_links,
                    provenance=a.provenance,
                )
            )
        goals.append(
            ExtractedGoal(
                goal_id=goal_id,
                goal_number=goal_number,
                goal_type=g.goal_type,
                statement=g.statement,
                lcff_priority=g.lcff_priority,
                target_group_id=g.target_group_id,
                metric_links=g.metric_links,
                actions=actions,
                provenance=g.provenance,
            )
        )

    return ExtractedPlan(
        plan_id=plan_id,
        school_id=school_id_nces or px.school_id,
        district_id=district_id,
        state_school_id=px.state_school_id,
        state_district_id=px.state_district_id,
        plan_type=px.plan_type,
        plan_year=plan_year,
        status=px.status,
        adopted_date=px.adopted_date,
        total_budget=px.total_budget,
        goals=goals,
        unresolved=px.unresolved,
        source=SourceRef(
            file=gs_uri,
            sha256=sha256,
            page_count=page_count,
            extracted_by=MODEL_ID,
            extracted_at=extracted_at,
        ),
    )


# --------------------------------------------------------------------------- #
# PDF helpers
# --------------------------------------------------------------------------- #
def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_year(y: Optional[str]) -> str:
    """'2025-2026' / '2025/26' / '2025-26' -> '2025-26' (compact YYYY-YY)."""
    if not y:
        return y or ""
    m = re.match(r"\s*(\d{4})\D+(\d{2,4})", y)
    return f"{m.group(1)}-{m.group(2)[-2:]}" if m else y.strip()


def count_pages(data: bytes) -> int:
    from pypdf import PdfReader
    from io import BytesIO

    return len(PdfReader(BytesIO(data)).pages)


def read_source(src: str) -> tuple[bytes, str, str]:
    """Read PDF bytes from a local path OR a remote URI (gs://, s3://, http…).

    Returns (bytes, display_name, default_source_uri). For a remote URI the URI
    itself becomes `source.file`; for a local path, its file:// URI. gs:// uses
    gcsfs via ADC — the same access the loaders use.
    """
    name = src.rstrip("/").rsplit("/", 1)[-1]
    if "://" in src and not src.startswith("file://"):
        import fsspec

        with fsspec.open(src, "rb") as fh:
            return fh.read(), name, src
    p = Path(src)
    return p.read_bytes(), p.name, p.resolve().as_uri()


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def extract_bytes(
    pdf_bytes: bytes,
    *,
    name: str,
    default_uri: str,
    district_id: str,
    school_id_nces: Optional[str],
    plan_year_hint: Optional[str],
    gs_uri: Optional[str] = None,
    context: Optional[str] = None,
    max_tokens: int = 16000,
    dry_run: bool = False,
) -> ExtractedPlan:
    """Core extraction — shared by the CLI and the FastAPI endpoint.

    `name` labels the source in logs; `default_uri` is recorded as `source.file`
    unless `gs_uri` overrides it. Returns a validated `ExtractedPlan` (never writes
    to the DB — that is the loader's job, after human review).
    """
    # Anthropic caps a request at ~32 MB; a huge scanned PDF 413s. Fail fast + clear.
    max_pdf_mb = 30
    if len(pdf_bytes) > max_pdf_mb * 1024 * 1024:
        raise RuntimeError(
            f"PDF too large for the API: {len(pdf_bytes) / 1024 / 1024:.0f} MB "
            f"> ~{max_pdf_mb} MB limit — needs compression or splitting"
        )
    b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
    sha = sha256_hex(pdf_bytes)
    pages = count_pages(pdf_bytes)
    uri = gs_uri or default_uri
    instruction = build_instruction(plan_year_hint, context)
    extracted_at = datetime.now(timezone.utc).isoformat()

    print(
        f"[extract] {name}: {len(pdf_bytes):,} bytes, {pages} pages, "
        f"sha256={sha[:12]}…, model={MODEL_ID}",
        file=sys.stderr,
    )

    if dry_run:
        print("[extract] --dry-run: skipping the billed API call.", file=sys.stderr)
        # Return a shell so callers can inspect source metadata without a model call.
        return assemble_plan(
            PlanExtraction(plan_type=PlanType.SPSA, plan_year=plan_year_hint or "unknown"),
            district_id=district_id,
            school_id_nces=school_id_nces,
            gs_uri=uri,
            sha256=sha,
            page_count=pages,
            extracted_at=extracted_at,
        )

    import anthropic

    # A forced tool call, NOT structured outputs (messages.parse). Structured outputs
    # compile the schema into a constrained-decoding grammar; this plan schema is deep
    # enough that the grammar exceeds Anthropic's size limit ("compiled grammar is too
    # large"). A non-strict tool passes the schema as guidance (no grammar), and we
    # validate the returned input with Pydantic ourselves.
    tool = {
        "name": "emit_plan",
        "description": "Return the extracted school-improvement plan as structured data.",
        "input_schema": PlanExtraction.model_json_schema(),
    }

    # Key: ANTHROPIC_API_KEY (dev) else Secret Manager `anthropic-api-key` via ADC.
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key_value)
    try:
        # Stream so a large max_tokens doesn't trip the SDK's 10-minute non-streaming
        # timeout guard; get_final_message() returns the fully assembled Message.
        with client.messages.stream(
            model=MODEL_ID,
            max_tokens=max_tokens,
            tools=[tool],
            tool_choice={"type": "tool", "name": "emit_plan"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": instruction},
                    ],
                }
            ],
        ) as stream:
            response = stream.get_final_message()
    except anthropic.APIStatusError as e:
        # Turn Anthropic's HTTP errors into a clean, actionable message (no stack trace).
        detail = getattr(e, "message", str(e))
        hint = ""
        low = detail.lower()
        if "credit balance" in low:
            hint = " → add credits at console.anthropic.com (Plans & Billing)"
        elif e.status_code == 401:
            hint = " → check the anthropic-api-key secret / ANTHROPIC_API_KEY"
        elif e.status_code == 429:
            hint = " → rate limited; retry shortly"
        raise RuntimeError(
            f"Anthropic API {e.status_code}: {detail} (request_id={getattr(e, 'request_id', None)}){hint}"
        )
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Anthropic API connection error: {e}")

    if response.stop_reason == "refusal":
        raise RuntimeError(f"model refused: {getattr(response, 'stop_details', None)}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "output truncated at max_tokens — raise --max-tokens (e.g. --max-tokens 32000)"
        )

    tool_use = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "emit_plan"),
        None,
    )
    if tool_use is None:
        raise RuntimeError("model did not return the emit_plan tool call")
    payload = tool_use.input
    # The model occasionally nests the whole payload under a single junk key (e.g. a
    # leaked "$PARAMETER_NAME" schema placeholder) instead of emitting fields at the top
    # level. Unwrap a lone dict-valued key that hides the real plan before validating.
    if isinstance(payload, dict) and "plan_type" not in payload and len(payload) == 1:
        inner = next(iter(payload.values()))
        if isinstance(inner, dict) and "plan_type" in inner:
            payload = inner
    try:
        px = PlanExtraction.model_validate(payload)
    except Exception as e:  # pydantic ValidationError
        raise RuntimeError(f"tool output failed schema validation: {e}")

    usage = response.usage
    print(
        f"[extract] ok: {len(px.goals)} goals; "
        f"tokens in={usage.input_tokens} out={usage.output_tokens}",
        file=sys.stderr,
    )

    return assemble_plan(
        px,
        district_id=district_id,
        school_id_nces=school_id_nces,
        gs_uri=uri,
        sha256=sha,
        page_count=pages,
        extracted_at=extracted_at,
    )


def extract(
    src: str,
    *,
    district_id: str,
    school_id_nces: Optional[str],
    plan_year_hint: Optional[str],
    gs_uri: Optional[str],
    context: Optional[str] = None,
    max_tokens: int = 16000,
    dry_run: bool = False,
) -> ExtractedPlan:
    """CLI convenience wrapper: read a local path or gs:// URI, delegate to `extract_bytes`."""
    data, name, default_uri = read_source(src)
    return extract_bytes(
        data,
        name=name,
        default_uri=default_uri,
        district_id=district_id,
        school_id_nces=school_id_nces,
        plan_year_hint=plan_year_hint,
        gs_uri=gs_uri,
        context=context,
        max_tokens=max_tokens,
        dry_run=dry_run,
    )


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Extract a CA school-improvement plan PDF to reviewable JSON.")
    ap.add_argument("pdf", help="local path OR gs:// URI to the source PDF")
    ap.add_argument("--out", type=Path, default=None, help="output JSON path (default: <basename>.json in cwd)")
    ap.add_argument(
        "--district-id",
        default="0622710",
        help="federal NCES LEAID (7-digit). Default is Long Beach Unified (0622710).",
    )
    ap.add_argument("--school-id", default=None, help="federal NCES school id (12-digit), if known")
    ap.add_argument("--plan-year", default=None, help="school-year hint, e.g. 2024-25")
    ap.add_argument("--gs-uri", default=None, help="gs:// URI to record as the canonical source")
    ap.add_argument("--context", default=None, help="district/format context injected into the prompt (goal_type scheme, structure notes)")
    ap.add_argument("--context-file", type=Path, default=None, help="read --context from a file (overrides --context)")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--dry-run", action="store_true", help="do everything except the API call")
    args = ap.parse_args(argv)

    context = args.context
    if args.context_file:
        context = args.context_file.read_text(encoding="utf-8")

    try:
        plan = extract(
            args.pdf,
            district_id=args.district_id,
            school_id_nces=args.school_id,
            plan_year_hint=args.plan_year,
            gs_uri=args.gs_uri,
            context=context,
            max_tokens=args.max_tokens,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, OSError) as e:
        print(f"error: cannot read {args.pdf}: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:  # Anthropic API error, refusal, truncation, parse failure
        print(f"error: {e}", file=sys.stderr)
        return 1

    basename = args.pdf.rstrip("/").rsplit("/", 1)[-1]
    out = args.out or Path(basename).with_suffix(".json")
    out.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print(f"[extract] wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
