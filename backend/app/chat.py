"""Conversational endpoint over the plan marts.

Claude answers questions about how Long Beach schools plan to improve attendance,
grounded in real data via an inline tool (`query_school_attendance_plans`) that calls
the mart. Manual tool-use loop, non-streaming (MVP). Reads only public data, so no
tenant/auth here — access is gated at the deploy layer (Cloud Run IAM).

Model: `settings.chat_model` (Haiku by default, for cost). Anthropic key resolves the
same way as the extractor (Secret Manager `anthropic-api-key`, env fallback).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db_public
from .marts import fetch_attendance_plans

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_TOKENS = 3000
MAX_TOOL_ITERS = 4
DISTRICT_ID = "0622500"  # Long Beach Unified (NCES LEAID)

SYSTEM = """You help education staff compare and understand how Long Beach Unified schools plan to improve student ATTENDANCE (chronic absenteeism), based on their School Plans for Student Achievement (SPSA).

Always call query_school_attendance_plans to get real data before answering — never invent schools, numbers, budgets, or plan text. Ground every claim in what the tool returns. Where it helps, cite a school's actual chronic-absenteeism rate, the specific funded strategies with their dollar amounts and funding source, and the verbatim plan language with its page number. Be concise and concrete; prefer specific comparisons over generalities. If the question isn't about attendance plans, say this prototype currently only covers Long Beach attendance plans."""

TOOLS = [
    {
        "name": "query_school_attendance_plans",
        "description": (
            "Return Long Beach Unified SPSA plan content about ATTENDANCE / chronic "
            "absenteeism: each school's attendance goals and the funded actions/strategies "
            "(with budgeted amounts, funding sources, and verbatim plan text + page "
            "citations), alongside the school's actual chronic-absenteeism rate. Use it to "
            "compare how schools plan to address attendance, or to dig into one school's "
            "strategies. Returns only attendance-related content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "string",
                    "description": "school level filter: 'High', 'Middle', or 'Elementary'. Omit for all levels.",
                },
                "school_name": {
                    "type": "string",
                    "description": "optional: limit to one school by (partial) name, e.g. 'Wilson'.",
                },
            },
        },
    }
]


class ChatTurn(BaseModel):
    role: str  # 'user' | 'assistant'
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatTurn]


def _run_tool(name: str, tool_input: dict, db: Session) -> dict:
    if name != "query_school_attendance_plans":
        return {"error": f"unknown tool: {name}"}
    data = fetch_attendance_plans(db, district_id=DISTRICT_ID, level=tool_input.get("level"))
    needle = (tool_input.get("school_name") or "").strip().lower()
    if needle:
        data["schools"] = [s for s in data["schools"] if needle in (s["school_name"] or "").lower()]
        data["school_count"] = len(data["schools"])
    return data


@router.post("")
def chat(req: ChatRequest, db: Session = Depends(get_db_public)) -> dict:
    """Answer a question about Long Beach attendance plans, grounded via the mart tool."""
    messages = [{"role": t.role, "content": t.content} for t in req.messages if t.content.strip()]
    if not messages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no messages")

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key_value)
    tools_used: list[str] = []
    resp = None
    try:
        for i in range(MAX_TOOL_ITERS + 1):
            resp = client.messages.create(
                model=settings.chat_model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
            )
            if resp.stop_reason == "refusal":
                return {"reply": "(the assistant declined to answer that.)", "tools_used": tools_used}
            if resp.stop_reason != "tool_use" or i == MAX_TOOL_ITERS:
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    tools_used.append(block.name)
                    out = _run_tool(block.name, block.input, db)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(out, default=str),
                    })
            messages.append({"role": "user", "content": results})
    except anthropic.APIStatusError as e:
        detail = getattr(e, "message", str(e))
        hint = " → add credits at console.anthropic.com" if "credit balance" in detail.lower() else ""
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"model error {e.status_code}: {detail}{hint}")
    except anthropic.APIConnectionError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"model connection error: {e}")

    reply = "".join(b.text for b in (resp.content if resp else []) if b.type == "text").strip()
    return {"reply": reply or "(no answer produced)", "tools_used": sorted(set(tools_used))}
