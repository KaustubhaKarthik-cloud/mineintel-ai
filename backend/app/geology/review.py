"""G2 geological fact review — approve / reject / correct without losing provenance.

Also enqueues review_required GeologicalFacts into the shared ReviewItem queue
(same mechanism as mining ExtractedFact review).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import Document, FactStatus, GeologicalFact, ReviewItem, ReviewStatus


class GeologicalReviewError(ValueError):
    pass


_FACT_TO_REVIEW_STATUS = {
    FactStatus.APPROVED.value: ReviewStatus.APPROVED.value,
    FactStatus.REJECTED.value: ReviewStatus.REJECTED.value,
    FactStatus.CORRECTED.value: ReviewStatus.CORRECTED.value,
    FactStatus.REVIEW_REQUIRED.value: ReviewStatus.PENDING.value,
}


def _priority_from_confidence(confidence: float) -> int:
    if confidence < 0.5:
        return 3
    if confidence < 0.7:
        return 2
    return 1


def _geo_display_value(row: GeologicalFact) -> tuple[Optional[str], Optional[str]]:
    """Original extracted value + unit for human review (never invent)."""
    value = (
        row.original_extracted_value
        or row.original_value
        or row.thickness
        or (
            f"{row.thickness_min}–{row.thickness_max}"
            if row.thickness_min and row.thickness_max
            else None
        )
        or row.depth
        or (
            f"{row.depth_min}–{row.depth_max}"
            if row.depth_min and row.depth_max
            else None
        )
        or row.seam_name
        or row.borehole_id
        or row.lithology
        or row.geological_formation
        or row.geological_structure
        or row.coal_quality_value
    )
    unit = (
        row.original_unit
        or row.thickness_unit
        or row.depth_unit
        or row.coal_quality_unit
    )
    return value, unit


def _geo_field_name(row: GeologicalFact) -> str:
    mk = (row.metric_kind or "").strip()
    return f"geological.{mk}" if mk else "geological_fact"


def _geo_entity_name(row: GeologicalFact) -> Optional[str]:
    return (
        row.seam_name
        or row.geological_formation
        or row.borehole_id
        or row.lithology
        or row.geological_structure
    )


def enqueue_geological_review_item(
    db: Session,
    fact: GeologicalFact,
    document: Optional[Document] = None,
) -> Optional[ReviewItem]:
    """Create a pending ReviewItem for a review_required GeologicalFact (idempotent)."""
    if fact.status != FactStatus.REVIEW_REQUIRED.value:
        return None

    existing = (
        db.query(ReviewItem)
        .filter(
            ReviewItem.geological_fact_id == fact.id,
            ReviewItem.status == ReviewStatus.PENDING.value,
        )
        .first()
    )
    if existing:
        return existing

    doc = document
    if doc is None:
        doc = db.get(Document, fact.document_id)

    value, unit = _geo_display_value(fact)
    item = ReviewItem(
        document_id=fact.document_id,
        geological_fact_id=fact.id,
        field_name=_geo_field_name(fact),
        extracted_value=value,
        original_unit=unit,
        entity_name=_geo_entity_name(fact),
        evidence_text=fact.evidence_text,
        page_number=fact.source_page,
        source_document=doc.original_filename if doc else None,
        confidence=float(fact.extraction_confidence or 0.0),
        status=ReviewStatus.PENDING.value,
        priority=_priority_from_confidence(float(fact.extraction_confidence or 0.0)),
    )
    db.add(item)
    db.flush()
    return item


def delete_geological_review_items_for_document(db: Session, document_id: str) -> int:
    """Remove ReviewItems linked to geological facts for a document (before re-extract)."""
    q = db.query(ReviewItem).filter(
        ReviewItem.document_id == document_id,
        ReviewItem.geological_fact_id.isnot(None),
    )
    count = q.count()
    q.delete(synchronize_session=False)
    db.flush()
    return count


def mirror_geological_fact_to_review_items(db: Session, fact: GeologicalFact) -> None:
    """Keep linked ReviewItems in sync when a GeologicalFact is reviewed elsewhere."""
    target = _FACT_TO_REVIEW_STATUS.get(fact.status)
    if not target:
        return
    items = (
        db.query(ReviewItem)
        .filter(ReviewItem.geological_fact_id == fact.id)
        .all()
    )
    now = datetime.now(timezone.utc)
    for item in items:
        if item.status == target:
            continue
        item.status = target
        if target != ReviewStatus.PENDING.value:
            item.reviewed_at = item.reviewed_at or now
            if fact.corrected_by and not item.reviewer:
                item.reviewer = fact.corrected_by
            if fact.correction_reason and not item.review_notes:
                item.review_notes = fact.correction_reason
            if fact.corrected_value is not None:
                item.corrected_value = fact.corrected_value
            if fact.corrected_unit is not None:
                item.corrected_unit = fact.corrected_unit
        db.add(item)
    db.flush()


def sync_geological_review_queue(db: Session) -> int:
    """Ensure review_required geo facts have pending ReviewItems; close stale ones.

    Returns number of newly enqueued items. Safe to call from the list endpoint
    so facts persisted before this wiring still appear in the Review Queue.
    """
    created = 0
    # Close pending queue rows whose fact is no longer review_required
    pending_geo = (
        db.query(ReviewItem)
        .filter(
            ReviewItem.geological_fact_id.isnot(None),
            ReviewItem.status == ReviewStatus.PENDING.value,
        )
        .all()
    )
    for item in pending_geo:
        fact = db.get(GeologicalFact, item.geological_fact_id)
        if fact is None:
            db.delete(item)
            continue
        if fact.status != FactStatus.REVIEW_REQUIRED.value:
            mirror_geological_fact_to_review_items(db, fact)

    # Enqueue missing review_required facts
    open_ids = {
        r[0]
        for r in db.query(ReviewItem.geological_fact_id)
        .filter(
            ReviewItem.geological_fact_id.isnot(None),
            ReviewItem.status == ReviewStatus.PENDING.value,
        )
        .all()
    }
    orphan_facts = (
        db.query(GeologicalFact)
        .filter(GeologicalFact.status == FactStatus.REVIEW_REQUIRED.value)
        .all()
    )
    for fact in orphan_facts:
        if fact.id in open_ids:
            continue
        if enqueue_geological_review_item(db, fact) is not None:
            created += 1

    if created or pending_geo:
        db.commit()
    return created


def review_geological_fact(
    db: Session,
    fact_id: str,
    *,
    action: str,
    corrected_value: Optional[str] = None,
    corrected_unit: Optional[str] = None,
    reviewer: Optional[str] = None,
    reason: Optional[str] = None,
) -> GeologicalFact:
    """Apply human review to a GeologicalFact.

    Never promotes review_required → verified silently outside explicit approve/correct.
    Corrections preserve original_extracted_value and bump fact_version.
    """
    row = db.get(GeologicalFact, fact_id)
    if not row:
        raise GeologicalReviewError("Geological fact not found.")
    act = (action or "").lower().strip()
    if act == "approve":
        row.status = FactStatus.APPROVED.value
        row.corrected_by = reviewer
        row.corrected_at = datetime.now(timezone.utc)
        if reason:
            row.correction_reason = reason
    elif act == "reject":
        row.status = FactStatus.REJECTED.value
        row.corrected_by = reviewer
        row.corrected_at = datetime.now(timezone.utc)
        row.correction_reason = reason
    elif act == "correct":
        if corrected_value is None or str(corrected_value).strip() == "":
            raise GeologicalReviewError("corrected_value is required for corrections.")
        if not row.original_extracted_value:
            # Snapshot first correction's pre-state
            row.original_extracted_value = (
                row.original_value
                or row.thickness
                or (
                    f"{row.thickness_min}–{row.thickness_max}"
                    if row.thickness_min and row.thickness_max
                    else None
                )
                or row.depth
                or row.seam_name
                or row.borehole_id
                or row.lithology
                or row.geological_formation
            )
        row.corrected_value = str(corrected_value).strip()
        if corrected_unit is not None:
            row.corrected_unit = corrected_unit
        row.corrected_by = reviewer
        row.corrected_at = datetime.now(timezone.utc)
        row.correction_reason = reason
        row.fact_version = int(row.fact_version or 1) + 1
        row.status = FactStatus.CORRECTED.value
        # Apply correction to the active display fields without discarding originals
        mk = (row.metric_kind or "").lower()
        if "thickness" in mk or row.thickness or row.thickness_min:
            row.thickness = row.corrected_value
            if corrected_unit:
                row.thickness_unit = corrected_unit
        elif "depth" in mk or row.depth:
            row.depth = row.corrected_value
            if corrected_unit:
                row.depth_unit = corrected_unit
        elif mk == "seam" or row.seam_name:
            row.seam_name = row.corrected_value
        elif mk == "borehole" or row.borehole_id:
            row.borehole_id = row.corrected_value
        elif mk == "lithology":
            row.lithology = row.corrected_value
        elif mk == "formation":
            row.geological_formation = row.corrected_value
    else:
        raise GeologicalReviewError(f"Unknown review action: {action}")
    db.add(row)
    db.flush()
    mirror_geological_fact_to_review_items(db, row)
    return row


def geological_fact_review_dict(row: GeologicalFact) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status,
        "metric_kind": row.metric_kind,
        "original_value": row.original_value,
        "original_extracted_value": row.original_extracted_value,
        "corrected_value": row.corrected_value,
        "corrected_unit": row.corrected_unit,
        "corrected_by": row.corrected_by,
        "corrected_at": row.corrected_at.isoformat() if row.corrected_at else None,
        "correction_reason": row.correction_reason,
        "fact_version": row.fact_version,
        "source_page": row.source_page,
        "document_id": row.document_id,
    }
