"""Phase 5 validation & contradiction review APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ValidationConflict
from app.schemas import (
    ConflictActionRequest,
    ConflictEvidenceOut,
    ConflictListResponse,
    ConflictResolveRequest,
    ValidationConflictOut,
    ValidationRunResponse,
    ValidationStatsOut,
)
from app.validation.service import (
    ValidationError,
    confirm_conflict,
    dismiss_conflict,
    get_conflict,
    list_conflicts,
    resolve_conflict,
    run_validation,
    validation_stats,
)

router = APIRouter()


def _to_out(row: ValidationConflict) -> ValidationConflictOut:
    evidence = [
        ConflictEvidenceOut(
            id=e.id,
            document_id=e.document_id,
            document_page_id=e.document_page_id,
            extracted_fact_id=e.extracted_fact_id,
            document_name=e.document_name,
            document_version=e.document_version or 1,
            page_number=e.page_number,
            sheet_name=e.sheet_name,
            source_location=e.source_location,
            value=e.value,
            unit=e.unit,
            numeric_value=e.numeric_value,
            normalized_value=e.normalized_value,
            evidence_text=e.evidence_text,
            is_calculated=bool(e.is_calculated),
            label=e.label,
        )
        for e in (row.evidence_items or [])
    ]
    return ValidationConflictOut(
        id=row.id,
        fingerprint=row.fingerprint,
        conflict_type=row.conflict_type,
        entity_name=row.entity_name,
        field_name=row.field_name,
        period=row.period,
        status=row.status,
        severity=row.severity,
        description=row.description,
        selected_value=row.selected_value,
        selected_unit=row.selected_unit,
        resolution_reason=row.resolution_reason,
        reviewer=row.reviewer,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        evidence=evidence,
    )


@router.post("/run", response_model=ValidationRunResponse)
def validation_run(db: Session = Depends(get_db)) -> ValidationRunResponse:
    try:
        result = run_validation(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Validation run failed.") from exc
    return ValidationRunResponse(**result)


@router.get("/stats", response_model=ValidationStatsOut)
def validation_dashboard_stats(db: Session = Depends(get_db)) -> ValidationStatsOut:
    return ValidationStatsOut(**validation_stats(db))


@router.get("/conflicts", response_model=ConflictListResponse)
def get_conflicts(
    status: str | None = Query(default=None),
    document_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ConflictListResponse:
    rows = list_conflicts(db, status=status, document_id=document_id)
    items = [_to_out(r) for r in rows]
    return ConflictListResponse(total=len(items), items=items)


@router.get("/conflicts/{conflict_id}", response_model=ValidationConflictOut)
def get_conflict_detail(conflict_id: str, db: Session = Depends(get_db)) -> ValidationConflictOut:
    row = get_conflict(db, conflict_id)
    if not row:
        raise HTTPException(status_code=404, detail="Conflict not found.")
    return _to_out(row)


@router.post("/conflicts/{conflict_id}/confirm", response_model=ValidationConflictOut)
def confirm_conflict_endpoint(
    conflict_id: str,
    body: ConflictActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ValidationConflictOut:
    try:
        row = confirm_conflict(db, conflict_id, notes=(body.notes if body else None))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)


@router.post("/conflicts/{conflict_id}/dismiss", response_model=ValidationConflictOut)
def dismiss_conflict_endpoint(
    conflict_id: str,
    body: ConflictActionRequest | None = None,
    db: Session = Depends(get_db),
) -> ValidationConflictOut:
    try:
        row = dismiss_conflict(db, conflict_id, reason=(body.reason if body else None))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)


@router.post("/conflicts/{conflict_id}/resolve", response_model=ValidationConflictOut)
def resolve_conflict_endpoint(
    conflict_id: str,
    body: ConflictResolveRequest,
    db: Session = Depends(get_db),
) -> ValidationConflictOut:
    try:
        row = resolve_conflict(
            db,
            conflict_id,
            selected_value=body.selected_value,
            selected_unit=body.selected_unit,
            reason=body.reason,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(row)
