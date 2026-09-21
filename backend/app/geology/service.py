"""Geological pipeline service — classify + extract + persist with provenance."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.geology.classifier import ClassificationResult, classify_document_text
from app.geology.extractor import GeologicalFactDraft, extract_facts_from_pages
from app.geology.taxonomy import DocumentDomain
from app.models import Document, DocumentPage, GeologicalFact


def _joined_page_text(pages: list[DocumentPage]) -> str:
    parts = []
    for p in sorted(pages, key=lambda x: x.page_number):
        if p.text and p.text.strip():
            parts.append(p.text)
    return "\n\n".join(parts)


def classify_document(db: Session, document: Document) -> ClassificationResult:
    """Classify from persisted page text; store on document_category + meta."""
    pages = (
        db.query(DocumentPage)
        .filter(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_number)
        .all()
    )
    result = classify_document_text(
        _joined_page_text(pages),
        filename_hint=document.original_filename,
    )
    meta = dict(document.meta or {})
    meta["g1_classification"] = {
        "domain": result.domain,
        "label": result.label,
        "confidence": result.confidence,
        "scores": result.scores,
        "matched_terms": result.matched_terms,
        "method": result.method,
        "text_chars_used": result.text_chars_used,
    }
    document.meta = meta
    # Only overwrite free-text category when unset / generic
    current = (document.document_category or "").strip().lower()
    if current in {"", "general", "other", "uncategorized"}:
        document.document_category = result.label
    db.add(document)
    db.flush()
    return result


def _draft_to_row(
    document: Document,
    draft: GeologicalFactDraft,
    page_id_by_number: dict[int, str],
) -> GeologicalFact:
    from app.geology.entities import detect_value_qualifier, infer_metric_kind_from_fields

    page_id = None
    if draft.source_page is not None:
        page_id = page_id_by_number.get(draft.source_page)

    has_thickness = bool(draft.thickness or draft.thickness_min)
    has_depth = bool(draft.depth or draft.depth_min)
    metric_kind = infer_metric_kind_from_fields(
        metric_kind=draft.metric_kind,
        seam_name=draft.seam_name,
        borehole_id=draft.borehole_id,
        geological_formation=draft.geological_formation,
        lithology=draft.lithology,
        geological_structure=draft.geological_structure,
        coal_quality_parameter=draft.coal_quality_parameter,
        has_thickness=has_thickness,
        has_depth=has_depth,
        evidence_text=draft.evidence_text,
    )
    seam_status = draft.seam_status
    if not seam_status and draft.seam_name:
        seam_status = "named"
    if (draft.seam_status or "").lower() in {"uncorrelated", "unnamed"}:
        metric_kind = metric_kind or "seam"
    if draft.thickness_min and draft.thickness_max:
        original_value = f"{draft.thickness_min}–{draft.thickness_max}"
        original_unit = draft.thickness_unit
        qualifier = "range"
    elif draft.thickness:
        original_value = draft.thickness
        original_unit = draft.thickness_unit
        qualifier = detect_value_qualifier(draft.evidence_text) or detect_value_qualifier(
            draft.thickness
        )
    elif draft.depth_min and draft.depth_max:
        original_value = f"{draft.depth_min}–{draft.depth_max}"
        original_unit = draft.depth_unit
        qualifier = "range"
    elif draft.depth:
        original_value = draft.depth
        original_unit = draft.depth_unit
        qualifier = detect_value_qualifier(draft.evidence_text)
    elif draft.original_value and (draft.metric_kind or "") in {
        "resource",
        "reserve",
        "resource_quantity",
        "reserve_quantity",
    }:
        original_value = draft.original_value
        original_unit = draft.original_unit
        qualifier = None
    else:
        original_value = (
            draft.seam_name
            or draft.borehole_id
            or draft.lithology
            or draft.geological_formation
            or draft.geological_structure
            or draft.coal_quality_value
            or draft.original_value
        )
        original_unit = draft.coal_quality_unit or draft.original_unit
        qualifier = None

    return GeologicalFact(
        document_id=document.id,
        document_page_id=page_id,
        domain="geological",
        metric_kind=metric_kind,
        borehole_id=draft.borehole_id,
        seam_name=draft.seam_name,
        seam_status=seam_status,
        depth=draft.depth,
        depth_unit=draft.depth_unit,
        depth_normalized_m=draft.depth_normalized_m,
        thickness=draft.thickness,
        thickness_unit=draft.thickness_unit,
        thickness_normalized_m=draft.thickness_normalized_m,
        thickness_min=draft.thickness_min,
        thickness_max=draft.thickness_max,
        thickness_min_normalized_m=draft.thickness_min_normalized_m,
        thickness_max_normalized_m=draft.thickness_max_normalized_m,
        depth_min=draft.depth_min,
        depth_max=draft.depth_max,
        depth_min_normalized_m=draft.depth_min_normalized_m,
        depth_max_normalized_m=draft.depth_max_normalized_m,
        original_value=original_value,
        original_unit=original_unit,
        value_qualifier=qualifier,
        lithology=draft.lithology,
        geological_formation=draft.geological_formation,
        geological_structure=draft.geological_structure,
        coal_quality_parameter=draft.coal_quality_parameter,
        coal_quality_value=draft.coal_quality_value,
        coal_quality_unit=draft.coal_quality_unit,
        source_page=draft.source_page,
        source_location=draft.source_location,
        evidence_text=draft.evidence_text,
        extraction_confidence=draft.extraction_confidence,
        status=draft.status,
        original_extracted_value=original_value,
        fact_version=1,
        warnings=draft.warnings or None,
        table_context=draft.table_context,
        meta={
            "pipeline": "g1_rule_extractor",
            "g2": True,
            **({"metric_kind": metric_kind} if metric_kind else {}),
        },
    )


def extract_and_persist_geological_facts(
    db: Session,
    document: Document,
    *,
    replace_existing: bool = True,
) -> list[GeologicalFact]:
    """Extract geological facts from DocumentPage text and persist with provenance."""
    pages = (
        db.query(DocumentPage)
        .filter(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_number)
        .all()
    )
    page_id_by_number = {p.page_number: p.id for p in pages}
    drafts = extract_facts_from_pages(
        [(p.page_number, p.text or "", p.source_location) for p in pages]
    )

    if replace_existing:
        db.query(GeologicalFact).filter(GeologicalFact.document_id == document.id).delete()
        db.flush()

    rows: list[GeologicalFact] = []
    for draft in drafts:
        row = _draft_to_row(document, draft, page_id_by_number)
        db.add(row)
        rows.append(row)
    db.flush()

    meta = dict(document.meta or {})
    meta["g1_geological_extraction"] = {
        "facts_count": len(rows),
        "review_required": sum(1 for r in rows if r.status == "review_required"),
        "high_confidence": sum(1 for r in rows if r.status == "high_confidence"),
    }
    document.meta = meta
    db.add(document)
    db.flush()
    return rows


def run_geological_pipeline(db: Session, document: Document) -> dict[str, Any]:
    """Classify always; extract facts when domain is geological/exploration (or mixed strong geo score)."""
    classification = classify_document(db, document)
    facts: list[GeologicalFact] = []
    geo_score = (classification.scores or {}).get(DocumentDomain.GEOLOGICAL_EXPLORATION.value, 0.0)
    should_extract = (
        classification.domain == DocumentDomain.GEOLOGICAL_EXPLORATION.value
        or geo_score >= 6.0
    )
    if should_extract:
        facts = extract_and_persist_geological_facts(db, document, replace_existing=True)
    else:
        # Clear stale geological facts if document is reclassified away from geology
        db.query(GeologicalFact).filter(GeologicalFact.document_id == document.id).delete()
        meta = dict(document.meta or {})
        meta["g1_geological_extraction"] = {
            "facts_count": 0,
            "skipped": True,
            "reason": "domain_not_geological",
        }
        document.meta = meta
        db.add(document)
        db.flush()

    db.commit()
    db.refresh(document)
    return {
        "classification": {
            "domain": classification.domain,
            "label": classification.label,
            "confidence": classification.confidence,
            "scores": classification.scores,
            "matched_terms": classification.matched_terms,
        },
        "facts_count": len(facts),
        "fact_ids": [f.id for f in facts],
    }


def geological_fact_to_dict(row: GeologicalFact) -> dict[str, Any]:
    return {
        "id": row.id,
        "domain": getattr(row, "domain", None) or "geological",
        "metric_kind": getattr(row, "metric_kind", None),
        "borehole_id": row.borehole_id,
        "seam_name": row.seam_name,
        "seam_status": getattr(row, "seam_status", None),
        "depth": row.depth,
        "depth_unit": row.depth_unit,
        "depth_normalized_m": row.depth_normalized_m,
        "thickness": row.thickness,
        "thickness_unit": row.thickness_unit,
        "thickness_normalized_m": row.thickness_normalized_m,
        "thickness_min": getattr(row, "thickness_min", None),
        "thickness_max": getattr(row, "thickness_max", None),
        "thickness_min_normalized_m": getattr(row, "thickness_min_normalized_m", None),
        "thickness_max_normalized_m": getattr(row, "thickness_max_normalized_m", None),
        "depth_min": getattr(row, "depth_min", None),
        "depth_max": getattr(row, "depth_max", None),
        "depth_min_normalized_m": getattr(row, "depth_min_normalized_m", None),
        "depth_max_normalized_m": getattr(row, "depth_max_normalized_m", None),
        "original_value": getattr(row, "original_value", None),
        "original_unit": getattr(row, "original_unit", None),
        "value_qualifier": getattr(row, "value_qualifier", None),
        "lithology": row.lithology,
        "geological_formation": row.geological_formation,
        "geological_structure": row.geological_structure,
        "coal_quality_parameter": row.coal_quality_parameter,
        "coal_quality_value": row.coal_quality_value,
        "coal_quality_unit": row.coal_quality_unit,
        "source_document_id": row.document_id,
        "source_page": row.source_page,
        "source_location": row.source_location,
        "evidence_text": row.evidence_text,
        "extraction_confidence": row.extraction_confidence,
        "status": row.status,
        "original_extracted_value": getattr(row, "original_extracted_value", None),
        "corrected_value": getattr(row, "corrected_value", None),
        "corrected_unit": getattr(row, "corrected_unit", None),
        "corrected_by": getattr(row, "corrected_by", None),
        "corrected_at": row.corrected_at.isoformat() if getattr(row, "corrected_at", None) else None,
        "correction_reason": getattr(row, "correction_reason", None),
        "fact_version": getattr(row, "fact_version", None) or 1,
        "warnings": row.warnings,
        "table_context": row.table_context,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
