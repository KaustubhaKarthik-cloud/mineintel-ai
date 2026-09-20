"""Validation orchestration service (Phase 5)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models import (
    AuditLog,
    ConflictEvidence,
    ConflictStatus,
    Document,
    ExtractedFact,
    FactStatus,
    ValidationConflict,
)
from app.validation.conflict_detector import (
    ConflictDraft,
    detect_cross_document_conflicts,
    detect_reported_calculated_discrepancies,
)


class ValidationError(RuntimeError):
    pass


TERMINAL_STATUSES = {
    ConflictStatus.RESOLVED.value,
    ConflictStatus.DISMISSED.value,
    ConflictStatus.CONFIRMED.value,
}


def _doc_meta(db: Session) -> dict[str, tuple[str, int]]:
    docs = db.query(Document).all()
    return {d.id: (d.original_filename, d.version or 1) for d in docs}


def _active_facts(db: Session) -> list[ExtractedFact]:
    """Facts from latest document versions only (obsolete versions excluded)."""
    docs = db.query(Document).all()
    latest: dict[str, Document] = {}
    for d in docs:
        key = (d.original_filename or d.filename).lower()
        prev = latest.get(key)
        if prev is None or (d.version or 1) >= (prev.version or 1):
            latest[key] = d
    latest_ids = {d.id for d in latest.values()}
    facts = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.document_id.in_(latest_ids) if latest_ids else False)
        .filter(ExtractedFact.status != FactStatus.REJECTED.value)
        .all()
    )
    return facts


def run_validation(db: Session) -> dict:
    facts = _active_facts(db)
    meta = _doc_meta(db)
    drafts: list[ConflictDraft] = []
    drafts.extend(detect_cross_document_conflicts(facts, meta))
    drafts.extend(detect_reported_calculated_discrepancies(facts, meta))

    created = 0
    refreshed = 0
    unchanged = 0
    open_fps = {d.fingerprint for d in drafts}

    for draft in drafts:
        existing = (
            db.query(ValidationConflict)
            .filter(ValidationConflict.fingerprint == draft.fingerprint)
            .first()
        )
        if existing and existing.status in TERMINAL_STATUSES:
            unchanged += 1
            continue

        if existing:
            # Refresh open conflict evidence
            db.query(ConflictEvidence).filter(ConflictEvidence.conflict_id == existing.id).delete()
            existing.conflict_type = draft.conflict_type
            existing.entity_name = draft.entity_name
            existing.field_name = draft.field_name
            existing.period = draft.period
            existing.severity = draft.severity
            existing.description = draft.description
            existing.status = ConflictStatus.REVIEW_REQUIRED.value
            existing.updated_at = datetime.now(timezone.utc)
            _add_evidence(db, existing.id, draft)
            refreshed += 1
        else:
            row = ValidationConflict(
                fingerprint=draft.fingerprint,
                conflict_type=draft.conflict_type,
                entity_name=draft.entity_name,
                field_name=draft.field_name,
                period=draft.period,
                status=ConflictStatus.REVIEW_REQUIRED.value,
                severity=draft.severity,
                description=draft.description,
            )
            db.add(row)
            db.flush()
            _add_evidence(db, row.id, draft)
            created += 1

    # Auto-dismiss stale open conflicts no longer present (values now agree)
    q_stale = db.query(ValidationConflict).filter(
        ValidationConflict.status.in_(
            [ConflictStatus.REVIEW_REQUIRED.value, ConflictStatus.DETECTED.value]
        )
    )
    if open_fps:
        q_stale = q_stale.filter(~ValidationConflict.fingerprint.in_(open_fps))
    stale = q_stale.all()
    auto_cleared = 0
    for row in stale:
        row.status = ConflictStatus.DISMISSED.value
        row.resolution_reason = "Auto-cleared: conflict no longer present after re-validation."
        row.reviewer = "system"
        row.resolved_at = datetime.now(timezone.utc)
        auto_cleared += 1

    db.add(
        AuditLog(
            action="VALIDATION_RUN",
            entity_type="validation",
            entity_id=None,
            actor="system",
            details={
                "facts_scanned": len(facts),
                "drafts": len(drafts),
                "created": created,
                "refreshed": refreshed,
                "unchanged_terminal": unchanged,
                "auto_cleared": auto_cleared,
            },
        )
    )
    db.commit()
    return {
        "facts_scanned": len(facts),
        "conflicts_detected": len(drafts),
        "created": created,
        "refreshed": refreshed,
        "unchanged_terminal": unchanged,
        "auto_cleared": auto_cleared,
    }


def _add_evidence(db: Session, conflict_id: str, draft: ConflictDraft) -> None:
    for ev in draft.evidence:
        fact = ev.fact
        db.add(
            ConflictEvidence(
                conflict_id=conflict_id,
                document_id=fact.document_id,
                document_page_id=fact.document_page_id,
                extracted_fact_id=None if ev.is_calculated and ev.label == "calculated" else fact.id,
                document_name=ev.document_name,
                document_version=ev.document_version,
                page_number=fact.page_number,
                sheet_name=fact.sheet_name,
                source_location=fact.source_location,
                value=ev.value,
                unit=ev.unit,
                numeric_value=ev.numeric_value,
                normalized_value=ev.normalized_value,
                evidence_text=fact.evidence_text if ev.label != "calculated" else (
                    f"Calculated from production/target: {ev.value}%"
                ),
                is_calculated=ev.is_calculated,
                label=ev.label,
            )
        )


def list_conflicts(
    db: Session,
    *,
    status: Optional[str] = None,
    document_id: Optional[str] = None,
) -> list[ValidationConflict]:
    q = db.query(ValidationConflict).options(joinedload(ValidationConflict.evidence_items))
    if status:
        q = q.filter(ValidationConflict.status == status)
    rows = q.order_by(ValidationConflict.created_at.desc()).all()
    if document_id:
        rows = [
            r
            for r in rows
            if any(e.document_id == document_id for e in r.evidence_items)
        ]
    return rows


def get_conflict(db: Session, conflict_id: str) -> Optional[ValidationConflict]:
    return (
        db.query(ValidationConflict)
        .options(joinedload(ValidationConflict.evidence_items))
        .filter(ValidationConflict.id == conflict_id)
        .first()
    )


def _reviewer() -> str:
    return get_settings().validation_reviewer_default


def confirm_conflict(db: Session, conflict_id: str, notes: Optional[str] = None) -> ValidationConflict:
    row = get_conflict(db, conflict_id)
    if not row:
        raise ValidationError("Conflict not found.")
    prev = row.status
    row.status = ConflictStatus.CONFIRMED.value
    row.reviewer = _reviewer()
    if notes:
        row.resolution_reason = notes
    row.updated_at = datetime.now(timezone.utc)
    _audit(db, row, "VALIDATION_CONFIRM", prev)
    db.commit()
    db.refresh(row)
    return row


def dismiss_conflict(db: Session, conflict_id: str, reason: Optional[str] = None) -> ValidationConflict:
    row = get_conflict(db, conflict_id)
    if not row:
        raise ValidationError("Conflict not found.")
    prev = row.status
    row.status = ConflictStatus.DISMISSED.value
    row.reviewer = _reviewer()
    row.resolution_reason = reason or "Dismissed by reviewer."
    row.resolved_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    _audit(db, row, "VALIDATION_DISMISS", prev)
    db.commit()
    db.refresh(row)
    return row


def resolve_conflict(
    db: Session,
    conflict_id: str,
    *,
    selected_value: str,
    selected_unit: Optional[str] = None,
    reason: Optional[str] = None,
) -> ValidationConflict:
    row = get_conflict(db, conflict_id)
    if not row:
        raise ValidationError("Conflict not found.")
    if not (selected_value or "").strip():
        raise ValidationError("Selected verified value is required.")
    prev = row.status
    row.status = ConflictStatus.RESOLVED.value
    row.selected_value = selected_value.strip()
    row.selected_unit = selected_unit
    row.resolution_reason = reason or "Resolved by human reviewer."
    row.reviewer = _reviewer()
    row.resolved_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    _audit(
        db,
        row,
        "VALIDATION_RESOLVE",
        prev,
        extra={
            "selected_value": row.selected_value,
            "selected_unit": row.selected_unit,
            "reason": row.resolution_reason,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def _audit(
    db: Session,
    row: ValidationConflict,
    action: str,
    previous_status: str,
    extra: Optional[dict] = None,
) -> None:
    details = {
        "previous_status": previous_status,
        "new_status": row.status,
        "field_name": row.field_name,
        "entity_name": row.entity_name,
        "period": row.period,
    }
    if extra:
        details.update(extra)
    db.add(
        AuditLog(
            action=action,
            entity_type="validation_conflict",
            entity_id=row.id,
            actor=row.reviewer or _reviewer(),
            details=details,
        )
    )


def validation_stats(db: Session) -> dict:
    facts = db.query(ExtractedFact).filter(ExtractedFact.status != FactStatus.REJECTED.value).count()
    conflicts = db.query(ValidationConflict).all()
    by_status: dict[str, int] = {}
    for c in conflicts:
        by_status[c.status] = by_status.get(c.status, 0) + 1
    review_required = by_status.get(ConflictStatus.REVIEW_REQUIRED.value, 0) + by_status.get(
        ConflictStatus.DETECTED.value, 0
    )
    resolved = by_status.get(ConflictStatus.RESOLVED.value, 0)
    confirmed = by_status.get(ConflictStatus.CONFIRMED.value, 0)
    dismissed = by_status.get(ConflictStatus.DISMISSED.value, 0)
    open_conflicts = review_required + confirmed
    validated = max(0, facts - open_conflicts)  # approximate
    return {
        "facts": facts,
        "validated": validated,
        "review_required": review_required,
        "conflicts": open_conflicts,
        "resolved": resolved,
        "confirmed": confirmed,
        "dismissed": dismissed,
        "total_conflict_records": len(conflicts),
    }


def conflicts_for_fact_ids(db: Session, fact_ids: list[str]) -> dict[str, list[ValidationConflict]]:
    if not fact_ids:
        return {}
    rows = (
        db.query(ConflictEvidence)
        .options(joinedload(ConflictEvidence.conflict).joinedload(ValidationConflict.evidence_items))
        .filter(ConflictEvidence.extracted_fact_id.in_(fact_ids))
        .all()
    )
    out: dict[str, list[ValidationConflict]] = {}
    for ev in rows:
        if not ev.extracted_fact_id or not ev.conflict:
            continue
        if ev.conflict.status in {ConflictStatus.DISMISSED.value, ConflictStatus.RESOLVED.value}:
            continue
        out.setdefault(ev.extracted_fact_id, []).append(ev.conflict)
    return out


def conflicts_for_documents(db: Session, document_ids: list[str]) -> dict[str, list[ValidationConflict]]:
    if not document_ids:
        return {}
    rows = (
        db.query(ConflictEvidence)
        .options(
            joinedload(ConflictEvidence.conflict).joinedload(ValidationConflict.evidence_items)
        )
        .filter(ConflictEvidence.document_id.in_(document_ids))
        .all()
    )
    out: dict[str, list[ValidationConflict]] = {}
    for ev in rows:
        if not ev.document_id or not ev.conflict:
            continue
        if ev.conflict.status in {ConflictStatus.DISMISSED.value, ConflictStatus.RESOLVED.value}:
            continue
        bucket = out.setdefault(ev.document_id, [])
        if ev.conflict not in bucket:
            bucket.append(ev.conflict)
    return out
