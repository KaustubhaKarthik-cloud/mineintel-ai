"""Human review APIs (Phase 3 — DB-backed; Phase 1 demo fallback if empty)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.auth.deps import AuthUser, require_permission
from app.database import get_db
from app.models import FactCorrectionHistory, ReviewItem, ReviewStatus
from app.schemas import ReviewAction, ReviewItemOut, ReviewListResponse
from app.services import demo_data
from app.services.audit import write_audit
from app.services.review_service import ReviewServiceError, apply_review_action

router = APIRouter()


def _to_out(item: ReviewItem) -> ReviewItemOut:
    return ReviewItemOut(
        id=item.id,
        document_id=item.document_id,
        document_name=item.source_document,
        extracted_fact_id=item.extracted_fact_id,
        field_name=item.field_name,
        extracted_value=item.extracted_value,
        corrected_value=item.corrected_value,
        original_unit=item.original_unit,
        corrected_unit=item.corrected_unit,
        entity_name=item.entity_name,
        financial_year=item.financial_year,
        evidence_text=item.evidence_text,
        page_number=item.page_number,
        sheet_name=item.sheet_name,
        source_document=item.source_document,
        confidence=item.confidence,
        status=item.status,
        priority=item.priority,
        mine_name=item.entity_name,
        reviewer=item.reviewer,
        review_notes=item.review_notes,
        created_at=item.created_at,
        reviewed_at=item.reviewed_at,
    )


def _demo_action(review_id: str, body: ReviewAction) -> ReviewItemOut | None:
    for r in demo_data.DEMO_REVIEWS:
        if r["id"] == review_id:
            if body.action == "approve":
                r["status"] = "approved"
            elif body.action == "reject":
                r["status"] = "rejected"
            elif body.action == "correct":
                r["status"] = "corrected"
                r["corrected_value"] = body.corrected_value
            else:
                raise HTTPException(status_code=400, detail="Invalid action")
            return ReviewItemOut(**r)
    return None


@router.get("", response_model=ReviewListResponse)
def list_reviews(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("review.act")),
) -> ReviewListResponse:
    items = db.query(ReviewItem).order_by(desc(ReviewItem.created_at)).all()
    if items:
        out = [_to_out(i) for i in items]
        pending = sum(1 for i in out if i.status == ReviewStatus.PENDING.value)
        return ReviewListResponse(total=len(out), pending=pending, items=out)

    demo = [ReviewItemOut(**r) for r in demo_data.DEMO_REVIEWS]
    pending = sum(1 for r in demo if r.status == "pending")
    return ReviewListResponse(total=len(demo), pending=pending, items=demo)


@router.get("/corrections/history")
def correction_history(
    fact_id: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("review.act")),
) -> dict[str, Any]:
    q = db.query(FactCorrectionHistory).order_by(desc(FactCorrectionHistory.created_at))
    if fact_id:
        q = q.filter(FactCorrectionHistory.extracted_fact_id == fact_id)
    rows = q.limit(min(max(limit, 1), 500)).all()
    return {
        "total": len(rows),
        "items": [
            {
                "id": r.id,
                "extracted_fact_id": r.extracted_fact_id,
                "document_id": r.document_id,
                "review_item_id": r.review_item_id,
                "field_name": r.field_name,
                "original_value": r.original_value,
                "original_unit": r.original_unit,
                "corrected_value": r.corrected_value,
                "corrected_unit": r.corrected_unit,
                "reviewer": r.reviewer,
                "reason": r.reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/{review_id}", response_model=ReviewItemOut)
def get_review(
    review_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("review.act")),
) -> ReviewItemOut:
    item = db.query(ReviewItem).filter(ReviewItem.id == review_id).first()
    if item:
        return _to_out(item)
    for r in demo_data.DEMO_REVIEWS:
        if r["id"] == review_id:
            return ReviewItemOut(**r)
    raise HTTPException(status_code=404, detail="Review item not found")


@router.post("/{review_id}/action", response_model=ReviewItemOut)
def review_action(
    review_id: str,
    body: ReviewAction,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("review.act")),
) -> ReviewItemOut:
    if not body.reviewer:
        body.reviewer = user.username
    try:
        return _to_out(apply_review_action(db, review_id, body))
    except ReviewServiceError as exc:
        demo = _demo_action(review_id, body)
        if demo:
            write_audit(
                db,
                action=f"REVIEW_{body.action.upper()}_DEMO",
                actor=user.username,
                entity_type="review_item",
                entity_id=review_id,
                details={"demo": True},
                ip_address=request.client.host if request.client else None,
                commit=True,
            )
            return demo
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{review_id}/approve", response_model=ReviewItemOut)
def approve_review(
    review_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("review.act")),
) -> ReviewItemOut:
    return review_action(review_id, ReviewAction(action="approve"), request, db, user)


@router.post("/{review_id}/reject", response_model=ReviewItemOut)
def reject_review(
    review_id: str,
    request: Request,
    body: ReviewAction | None = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("review.act")),
) -> ReviewItemOut:
    payload = body or ReviewAction(action="reject")
    payload.action = "reject"
    return review_action(review_id, payload, request, db, user)


@router.post("/{review_id}/correct", response_model=ReviewItemOut)
def correct_review(
    review_id: str,
    body: ReviewAction,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("review.act")),
) -> ReviewItemOut:
    body.action = "correct"
    return review_action(review_id, body, request, db, user)
