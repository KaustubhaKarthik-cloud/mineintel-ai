"""Phase 3 extraction orchestration service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.ai_extraction.confidence import classify_status, score_fact
from app.ai_extraction.llm import LLMError, LLMProvider, get_llm_provider
from app.ai_extraction.validator import detect_achievement_discrepancy, validate_draft
from app.config import get_settings
from app.models import (
    AuditLog,
    Document,
    DocumentPage,
    DocumentStatus,
    ExtractedFact,
    ExtractionJob,
    ExtractionJobStatus,
    FactStatus,
    ReviewItem,
    ReviewStatus,
    SourceType,
)


class ExtractionServiceError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _page_is_ocr(page: DocumentPage) -> bool:
    return page.source_type in {SourceType.OCR_PAGE.value, SourceType.IMAGE.value}


def _batches(pages: list[DocumentPage], size: int) -> list[list[DocumentPage]]:
    return [pages[i : i + size] for i in range(0, len(pages), size)]


def _priority_from_confidence(confidence: float) -> int:
    if confidence < 0.5:
        return 3
    if confidence < 0.7:
        return 2
    return 1


def run_extraction(
    db: Session,
    document_id: str,
    provider: Optional[LLMProvider] = None,
) -> ExtractionJob:
    doc = (
        db.query(Document)
        .options(joinedload(Document.pages))
        .filter(Document.id == document_id)
        .first()
    )
    if not doc:
        raise ExtractionServiceError("Document not found.")
    if doc.status not in {
        DocumentStatus.COMPLETED.value,
        DocumentStatus.EXTRACTED.value,
        DocumentStatus.REVIEW_REQUIRED.value,
        DocumentStatus.PENDING_REVIEW.value,
        DocumentStatus.APPROVED.value,
    }:
        raise ExtractionServiceError(
            "Document must complete Phase 2 processing before AI extraction."
        )
    if not doc.pages:
        raise ExtractionServiceError("Document has no extracted pages to analyze.")

    settings = get_settings()
    llm = provider or get_llm_provider()

    job = ExtractionJob(
        document_id=doc.id,
        status=ExtractionJobStatus.RUNNING.value,
        provider=llm.name,
        started_at=_utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Clear previous Phase 3 facts/reviews for re-extract
    old_facts = db.query(ExtractedFact).filter(ExtractedFact.document_id == doc.id).all()
    old_ids = [f.id for f in old_facts]
    if old_ids:
        db.query(ReviewItem).filter(ReviewItem.extracted_fact_id.in_(old_ids)).delete(
            synchronize_session=False
        )
        db.query(ExtractedFact).filter(ExtractedFact.document_id == doc.id).delete(
            synchronize_session=False
        )
        db.commit()

    all_warnings: list[str] = []
    created_facts: list[ExtractedFact] = []
    pages_sorted = sorted(doc.pages, key=lambda p: p.page_number)
    page_by_number = {p.page_number: p for p in pages_sorted}

    try:
        for batch in _batches(pages_sorted, settings.extraction_page_batch_size):
            payload = [
                {
                    "page_id": p.id,
                    "page_number": p.page_number,
                    "source_type": p.source_type,
                    "sheet_name": p.sheet_name,
                    "source_location": p.source_location,
                    "text": p.text or "",
                    "is_ocr": _page_is_ocr(p),
                }
                for p in batch
            ]
            batch_text = "\n".join(p.text or "" for p in batch)
            response = llm.extract_structured_information(doc.original_filename, payload)
            all_warnings.extend(response.warnings or [])

            for draft in response.facts:
                ok, v_warnings, numeric = validate_draft(draft, batch_text)
                all_warnings.extend(v_warnings)
                if not ok:
                    continue

                page = None
                if draft.page_number is not None:
                    page = page_by_number.get(draft.page_number)
                if page is None and len(batch) == 1:
                    page = batch[0]

                is_ocr = _page_is_ocr(page) if page else False
                evidence_ok = bool(draft.evidence) and (
                    draft.evidence.lower() in batch_text.lower()
                    or any(
                        tok.lower() in batch_text.lower()
                        for tok in str(draft.evidence).split()
                        if len(tok) > 3
                    )
                )
                page_meta = (page.content_meta or {}) if page else {}
                confidence = score_fact(
                    draft,
                    is_ocr_source=is_ocr or bool(draft.ambiguous),
                    schema_ok=True,
                    evidence_in_text=evidence_ok,
                    ocr_mean_confidence=page_meta.get("ocr_mean_confidence"),
                    ocr_low_confidence_decimals=page_meta.get("ocr_low_confidence_decimals"),
                )
                status = classify_status(confidence)

                fact = ExtractedFact(
                    document_id=doc.id,
                    document_page_id=page.id if page else None,
                    job_id=job.id,
                    field_name=draft.field,
                    value=str(draft.value) if draft.value is not None else None,
                    numeric_value=numeric,
                    unit=draft.unit,
                    entity_name=draft.mine or draft.entity,
                    financial_year=draft.financial_year,
                    page_number=draft.page_number or (page.page_number if page else None),
                    sheet_name=draft.sheet_name or (page.sheet_name if page else None),
                    source_location=draft.source_location
                    or (page.source_location if page else None),
                    evidence_text=draft.evidence,
                    confidence_score=confidence,
                    status=status,
                    is_ocr_source=is_ocr or bool(draft.ambiguous),
                    warnings=v_warnings or None,
                )
                db.add(fact)
                created_facts.append(fact)

        db.flush()

        # Reported vs calculated achievement
        by_entity: dict[str, dict[str, ExtractedFact]] = {}
        for fact in created_facts:
            key = (fact.entity_name or "") + "|" + (fact.financial_year or "")
            by_entity.setdefault(key, {})[fact.field_name] = fact

        for _key, fields in by_entity.items():
            prod = fields.get("production")
            target = fields.get("production_target")
            reported = fields.get("achievement_percentage")
            calculated, warn = detect_achievement_discrepancy(
                prod.numeric_value if prod else None,
                target.numeric_value if target else None,
                reported.numeric_value if reported else None,
            )
            if calculated is not None and prod and target:
                calc_fact = ExtractedFact(
                    document_id=doc.id,
                    document_page_id=prod.document_page_id,
                    job_id=job.id,
                    field_name="achievement_percentage_calculated",
                    value=str(calculated),
                    numeric_value=calculated,
                    unit="%",
                    entity_name=prod.entity_name,
                    financial_year=prod.financial_year,
                    page_number=prod.page_number,
                    sheet_name=prod.sheet_name,
                    source_location=prod.source_location,
                    evidence_text=(
                        f"Calculated from production={prod.value} {prod.unit or ''} "
                        f"and target={target.value} {target.unit or ''}."
                    ),
                    confidence_score=min(
                        prod.confidence_score,
                        target.confidence_score,
                    ),
                    status=FactStatus.EXTRACTED.value,
                    is_ocr_source=False,
                    is_calculated=True,
                    related_fact_id=reported.id if reported else None,
                    warnings=[warn] if warn else None,
                )
                db.add(calc_fact)
                created_facts.append(calc_fact)
                if warn:
                    all_warnings.append(warn)
                    if reported:
                        reported.warnings = list(set((reported.warnings or []) + [warn]))
                        if reported.status == FactStatus.HIGH_CONFIDENCE.value:
                            reported.status = FactStatus.REVIEW_REQUIRED.value

        db.flush()

        review_count = 0
        high_count = 0
        for fact in created_facts:
            if fact.status == FactStatus.HIGH_CONFIDENCE.value:
                high_count += 1
            if fact.status == FactStatus.REVIEW_REQUIRED.value and not fact.is_calculated:
                review_count += 1
                db.add(
                    ReviewItem(
                        document_id=doc.id,
                        extracted_fact_id=fact.id,
                        field_name=fact.field_name,
                        extracted_value=fact.value,
                        original_unit=fact.unit,
                        entity_name=fact.entity_name,
                        financial_year=fact.financial_year,
                        evidence_text=fact.evidence_text,
                        page_number=fact.page_number,
                        sheet_name=fact.sheet_name,
                        source_document=doc.original_filename,
                        confidence=fact.confidence_score,
                        status=ReviewStatus.PENDING.value,
                        priority=_priority_from_confidence(fact.confidence_score),
                    )
                )

        job.status = ExtractionJobStatus.COMPLETED.value
        job.facts_count = len(created_facts)
        job.review_count = review_count
        job.high_confidence_count = high_count
        job.warnings = all_warnings[:50] or None
        job.completed_at = _utcnow()

        confidences = [f.confidence_score for f in created_facts if not f.is_calculated]
        doc.extraction_completed = True
        doc.overall_confidence = (
            round(sum(confidences) / len(confidences), 3) if confidences else None
        )
        if review_count:
            doc.status = DocumentStatus.REVIEW_REQUIRED.value
        else:
            doc.status = DocumentStatus.EXTRACTED.value

        db.add(
            AuditLog(
                action="AI_EXTRACT",
                entity_type="document",
                entity_id=doc.id,
                actor="system",
                details={
                    "job_id": job.id,
                    "facts": len(created_facts),
                    "review": review_count,
                    "provider": llm.name,
                },
            )
        )
        db.commit()
        db.refresh(job)
        return job

    except LLMError as exc:
        job.status = ExtractionJobStatus.FAILED.value
        job.error_message = str(exc)
        job.completed_at = _utcnow()
        db.commit()
        db.refresh(job)
        raise ExtractionServiceError(str(exc)) from exc
    except ExtractionServiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        job.status = ExtractionJobStatus.FAILED.value
        job.error_message = "Extraction failed. Please try again."
        job.completed_at = _utcnow()
        job.warnings = [str(exc)[:300]]
        db.commit()
        db.refresh(job)
        raise ExtractionServiceError("Extraction failed. Please try again.") from exc


def run_batch_extraction(db: Session, document_ids: list[str]) -> list[dict[str, Any]]:
    results = []
    for doc_id in document_ids:
        try:
            job = run_extraction(db, doc_id)
            results.append(
                {
                    "document_id": doc_id,
                    "job_id": job.id,
                    "status": job.status,
                    "facts_count": job.facts_count,
                    "review_count": job.review_count,
                }
            )
        except ExtractionServiceError as exc:
            results.append({"document_id": doc_id, "status": "failed", "error": str(exc)})
    return results
