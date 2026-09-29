"""Topics API — corpus topics, evidence links, grounded summaries."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.deps import AuthUser, require_permission
from app.database import get_db
from app.topics import service as topics_service
from app.topics.extractor import extract_topics_from_corpus

router = APIRouter()


@router.get("")
def list_topics(
    refresh: bool = Query(False, description="Re-scan corpus before listing"),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("topics")),
) -> dict:
    if refresh:
        extract_topics_from_corpus(db)
    else:
        topics_service.ensure_topics(db)
    return {"items": topics_service.list_topics(db)}


@router.post("/extract")
def extract_topics(
    document_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("topics")),
) -> dict:
    return extract_topics_from_corpus(db, document_id=document_id)


@router.get("/{topic_id}")
def get_topic(
    topic_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("topics")),
) -> dict:
    detail = topics_service.get_topic(db, topic_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return detail


@router.post("/{topic_id}/summary")
def summarize_topic(
    topic_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("topics")),
) -> dict:
    result = topics_service.summarize_topic(db, topic_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result
