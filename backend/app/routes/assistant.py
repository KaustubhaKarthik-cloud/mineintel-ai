"""AI Assistant APIs — Phase 6 evidence-grounded Q&A."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.assistant.service import ask_assistant, build_chart_only
from app.database import get_db
from app.schemas import (
    AssistantChartRequest,
    AssistantQueryRequest,
    ChatRequest,
    ChatResponse,
    ChatSource,
)

router = APIRouter()


def _to_chat_response(result: dict) -> ChatResponse:
    sources = [
        ChatSource(
            document_id=s["document_id"],
            document_name=s["document_name"],
            snippet=s["snippet"],
            relevance=float(s.get("relevance") or 0),
            page=s.get("page"),
            sheet_name=s.get("sheet_name"),
        )
        for s in result.get("sources") or []
    ]
    return ChatResponse(
        session_id=result["session_id"],
        reply=result.get("reply") or result.get("answer") or "",
        sources=sources,
        query_type=result.get("query_type"),
        structured_evidence=result.get("structured_evidence") or [],
        rag_evidence=result.get("rag_evidence") or [],
        conflicts=result.get("conflicts") or [],
        chart=result.get("chart"),
        warnings=result.get("warnings") or [],
    )


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """Evidence-grounded assistant (Phase 6). Falls back to demo only if service fails hard."""
    try:
        result = ask_assistant(db, body.message, session_id=body.session_id)
        return _to_chat_response(result)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Assistant query failed.") from exc


@router.post("/query", response_model=ChatResponse)
def query(body: AssistantQueryRequest, db: Session = Depends(get_db)) -> ChatResponse:
    try:
        result = ask_assistant(
            db,
            body.question,
            session_id=body.session_id,
            history=body.history,
        )
        return _to_chat_response(result)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Assistant query failed.") from exc


@router.post("/chart")
def chart(body: AssistantChartRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return build_chart_only(
            db,
            entity=body.entity,
            metric=body.metric or "production",
            question=body.question,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Chart generation failed.") from exc


@router.get("/topics")
def list_topics_legacy():
    """Deprecated stub — use GET /api/topics."""
    return {"total": 0, "items": [], "deprecated": True, "use": "/api/topics"}


@router.get("/reports")
def list_reports_legacy():
    """Deprecated stub — use GET /api/reports."""
    return {"total": 0, "items": [], "deprecated": True, "use": "/api/reports"}


@router.get("/audit-logs")
def list_audit_logs_legacy():
    """Deprecated stub — use GET /api/system/audit-logs."""
    return {"total": 0, "items": [], "deprecated": True, "use": "/api/system/audit-logs"}
