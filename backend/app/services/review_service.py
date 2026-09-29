"""Human review actions for Phase 3 extracted facts + geological facts."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.geology.review import GeologicalReviewError, review_geological_fact
from app.models import (
    ExtractedFact,
    FactCorrectionHistory,
    FactStatus,
    ReviewItem,
    ReviewStatus,
)
from app.schemas import ReviewAction
from app.services.audit import write_audit


class ReviewServiceError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def apply_review_action(db: Session, review_id: str, body: ReviewAction) -> ReviewItem:
    item = db.query(ReviewItem).filter(ReviewItem.id == review_id).first()
    if not item:
        raise ReviewServiceError("Review item not found.")
    if item.status != ReviewStatus.PENDING.value:
        raise ReviewServiceError("This review item has already been resolved.")

    fact: ExtractedFact | None = None
    if item.extracted_fact_id:
        fact = db.query(ExtractedFact).filter(ExtractedFact.id == item.extracted_fact_id).first()

    action = body.action.lower().strip()
    item.reviewer = body.reviewer
    item.review_notes = body.review_notes
    item.reviewed_at = _utcnow()

    if action == "approve":
        item.status = ReviewStatus.APPROVED.value
        if fact:
            fact.status = FactStatus.APPROVED.value
        if item.geological_fact_id:
            try:
                review_geological_fact(
                    db,
                    item.geological_fact_id,
                    action="approve",
                    reviewer=body.reviewer,
                    reason=body.review_notes,
                )
            except GeologicalReviewError as exc:
                raise ReviewServiceError(str(exc)) from exc
    elif action == "reject":
        item.status = ReviewStatus.REJECTED.value
        if fact:
            fact.status = FactStatus.REJECTED.value
        if item.geological_fact_id:
            try:
                review_geological_fact(
                    db,
                    item.geological_fact_id,
                    action="reject",
                    reviewer=body.reviewer,
                    reason=body.review_notes,
                )
            except GeologicalReviewError as exc:
                raise ReviewServiceError(str(exc)) from exc
    elif action == "correct":
        if body.corrected_value is None or str(body.corrected_value).strip() == "":
            raise ReviewServiceError("corrected_value is required for corrections.")
        # Preserve original AI value on the review row / fact
        item.corrected_value = str(body.corrected_value).strip()
        if body.corrected_unit is not None:
            item.corrected_unit = body.corrected_unit
        if body.entity_name is not None:
            item.entity_name = body.entity_name
        if body.financial_year is not None:
            item.financial_year = body.financial_year
        item.status = ReviewStatus.CORRECTED.value
        if item.geological_fact_id:
            try:
                review_geological_fact(
                    db,
                    item.geological_fact_id,
                    action="correct",
                    corrected_value=item.corrected_value,
                    corrected_unit=item.corrected_unit,
                    reviewer=body.reviewer,
                    reason=body.review_notes,
                )
            except GeologicalReviewError as exc:
                raise ReviewServiceError(str(exc)) from exc
        elif fact:
            original_value = fact.value
            original_unit = fact.unit
            # Keep original in meta history (never silently replace AI output only)
            history = list((fact.meta or {}).get("correction_history") or [])
            history.append(
                {
                    "original_value": original_value,
                    "corrected_value": item.corrected_value,
                    "original_unit": original_unit,
                    "corrected_unit": item.corrected_unit or original_unit,
                    "reviewer": body.reviewer,
                    "reason": body.review_notes,
                    "at": _utcnow().isoformat(),
                }
            )
            fact.meta = {
                **(fact.meta or {}),
                "correction_history": history,
                "original_ai_value": (fact.meta or {}).get("original_ai_value") or original_value,
                "verified_value": item.corrected_value,
            }
            db.add(
                FactCorrectionHistory(
                    extracted_fact_id=fact.id,
                    document_id=fact.document_id,
                    review_item_id=item.id,
                    field_name=fact.field_name,
                    original_value=original_value,
                    original_unit=original_unit,
                    corrected_value=item.corrected_value,
                    corrected_unit=item.corrected_unit or original_unit,
                    reviewer=body.reviewer,
                    reason=body.review_notes,
                )
            )
            fact.value = item.corrected_value
            if item.corrected_unit:
                fact.unit = item.corrected_unit
            if body.entity_name is not None:
                fact.entity_name = body.entity_name
            if body.financial_year is not None:
                fact.financial_year = body.financial_year
            try:
                fact.numeric_value = float(str(item.corrected_value).replace(",", ""))
            except ValueError:
                pass
            fact.status = FactStatus.CORRECTED.value
    else:
        raise ReviewServiceError("Invalid action. Use approve, reject, or correct.")

    write_audit(
        db,
        action=f"REVIEW_{action.upper()}",
        actor=body.reviewer,
        entity_type="review_item",
        entity_id=item.id,
        details={
            "field": item.field_name,
            "original": item.extracted_value,
            "corrected": item.corrected_value,
            "fact_id": item.extracted_fact_id or item.geological_fact_id,
            "geological_fact_id": item.geological_fact_id,
        },
    )
    db.commit()
    db.refresh(item)
    return item
