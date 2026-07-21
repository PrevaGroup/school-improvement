"""Plan-extraction endpoint — the PDF -> reviewable-JSON gate.

`POST /plans/extract` takes an uploaded SPSA/LCAP PDF and returns an `ExtractedPlan`
(the staging shape from `etl/ca/sip/schema.py`): goals, actions, and metric-link
proposals with page-level provenance. It writes NOTHING to the database — the JSON is
the human-review artifact that a reviewer approves before the augment loader writes
`plan_*` rows. See `etl/ca/sip/extract_sip.py` for the extraction core.

The route is gated behind `get_current_tenant` because it spends Anthropic tokens; the
extraction itself is model inference in the container, so it runs in a threadpool to
avoid blocking the event loop (a full plan can take a minute or two).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from etl.ca.sip.extract_sip import extract_bytes
from etl.ca.sip.schema import ExtractedPlan, ReviewStatus

from .db import get_db
from .plan_loader import load_plan
from .security import get_current_tenant

router = APIRouter(prefix="/plans", tags=["plans"])

_PDF_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


@router.post("/extract", response_model=ExtractedPlan)
async def extract_plan(
    file: UploadFile = File(..., description="the source SPSA / LCAP / CSI PDF"),
    district_id: str = Form("0622500", description="federal NCES LEAID (7-digit); default Long Beach Unified"),
    school_id: str | None = Form(None, description="federal NCES school id (12-digit), if known"),
    plan_year: str | None = Form(None, description="school-year hint, e.g. 2024-25"),
    gs_uri: str | None = Form(None, description="gs:// URI to record as the canonical source"),
    context: str | None = Form(None, description="district/format context injected into the prompt"),
    tenant_id: str = Depends(get_current_tenant),
) -> ExtractedPlan:
    if file.content_type and file.content_type not in _PDF_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"expected a PDF, got {file.content_type}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty upload")

    name = file.filename or "upload.pdf"
    try:
        return await run_in_threadpool(
            extract_bytes,
            data,
            name=name,
            default_uri=f"upload://{name}",
            district_id=district_id,
            school_id_nces=school_id,
            plan_year_hint=plan_year,
            gs_uri=gs_uri,
            context=context,
        )
    except RuntimeError as e:  # model refusal / truncation / parse failure
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"extraction failed: {e}")


@router.post("/load", status_code=status.HTTP_201_CREATED)
def load_plan_endpoint(
    plan: ExtractedPlan,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_db),
) -> dict:
    """Ingest an APPROVED ExtractedPlan into plan/plan_goal/plan_action for this tenant.

    The plan must be `review_status: approved` — the loader is the far side of the
    human-review gate, not a second extractor. Rows are written under the caller's
    verified tenant (RLS-enforced); the payload's own tenant, if any, is ignored.
    """
    if plan.review_status != ReviewStatus.approved:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"plan.review_status is '{plan.review_status.value}', must be 'approved' to load",
        )
    counts = load_plan(db, tenant_id, plan)
    return {"plan_id": plan.plan_id, "tenant_id": tenant_id, **counts}
