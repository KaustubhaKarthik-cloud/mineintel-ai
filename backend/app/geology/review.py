"""G2 geological fact review — approve / reject / correct without losing provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import FactStatus, GeologicalFact


class GeologicalReviewError(ValueError):
    pass


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
