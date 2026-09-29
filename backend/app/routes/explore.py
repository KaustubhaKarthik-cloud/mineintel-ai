"""Data exploration — documents, structured facts, and evidence chunks from the DB/index."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics.index_facts import index_fact_dimensions, list_analytics_documents, list_index_facts
from app.auth.deps import AuthUser, require_permission
from app.database import get_db
from app.models import Document, DocumentChunk, ExtractedFact

router = APIRouter()


@router.get("/dimensions")
def explore_dimensions(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    dims = index_fact_dimensions(db)
    docs = list_analytics_documents(db)
    # Also surface entities/metrics from AI-extracted facts
    for f in (
        db.query(ExtractedFact)
        .filter(ExtractedFact.numeric_value.isnot(None))
        .limit(5000)
        .all()
    ):
        if f.entity_name and f.entity_name not in dims["entities"]:
            dims["entities"].append(f.entity_name)
        if f.field_name and f.field_name not in dims["metrics"]:
            dims["metrics"].append(f.field_name)
        if f.financial_year and f.financial_year not in dims["periods"]:
            dims["periods"].append(f.financial_year)
    dims["entities"] = sorted(set(dims["entities"]), key=lambda x: x.lower())
    dims["metrics"] = sorted(set(dims["metrics"]))
    dims["periods"] = sorted(set(dims["periods"]))
    dims["documents"] = docs
    return dims


@router.get("/documents")
def explore_documents(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    items = list_analytics_documents(db)
    # Enrich with upload metadata
    by_id = {d.id: d for d in db.query(Document).all()}
    enriched = []
    for item in items:
        doc = by_id.get(item["id"])
        enriched.append(
            {
                **item,
                "document_type": doc.file_type if doc else item.get("file_type"),
                "document_category": doc.document_category if doc else None,
                "mine_name": doc.mine_name if doc else None,
                "ocr_completed": bool(doc.ocr_completed) if doc else False,
                "extraction_completed": bool(doc.extraction_completed) if doc else False,
                "embedding_completed": bool(doc.embedding_completed) if doc else False,
                "upload_date": item.get("created_at"),
            }
        )
    return {"total": len(enriched), "items": enriched}


@router.get("/structured-facts")
def explore_structured_facts(
    document_id: Optional[str] = None,
    entity: Optional[str] = None,
    metric: Optional[str] = None,
    fiscal_year: Optional[str] = None,
    reporting_month: Optional[str] = None,
    measurement_type: Optional[str] = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    doc_ids = [document_id] if document_id else None
    facts = list_index_facts(
        db,
        document_ids=doc_ids,
        entity=entity,
        metric=metric,
        fiscal_year=fiscal_year,
        reporting_month=reporting_month,
        measurement_type=measurement_type,
        limit=10000,
    )
    total = len(facts)
    page = facts[offset : offset + limit]
    items = [
        {
            "id": f.chunk_id,
            "entity": f.entity,
            "metric": f.metric,
            "value": f.value,
            "unit": f.unit,
            "fiscal_year": f.fiscal_year,
            "reporting_month": f.reporting_month,
            "measurement_type": f.measurement_type,
            "document_id": f.document_id,
            "document_name": f.document_name,
            "page": f.page,
            "table_id": f.table_id,
            "table_title": f.table_title,
            "column_path": f.column_path,
            "confidence": f.confidence,
            "evidence_text": f.evidence_text,
            "data_type": "structured_fact",
        }
        for f in page
    ]
    return {"total": total, "items": items, "offset": offset, "limit": limit}


@router.get("/extracted-facts")
def explore_extracted_facts(
    document_id: Optional[str] = None,
    entity: Optional[str] = None,
    metric: Optional[str] = None,
    fiscal_year: Optional[str] = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    q = db.query(ExtractedFact)
    if document_id:
        q = q.filter(ExtractedFact.document_id == document_id)
    if entity:
        q = q.filter(ExtractedFact.entity_name.ilike(f"%{entity}%"))
    if metric:
        q = q.filter(ExtractedFact.field_name.ilike(f"%{metric}%"))
    if fiscal_year:
        q = q.filter(ExtractedFact.financial_year.ilike(f"%{fiscal_year}%"))
    total = q.count()
    rows = q.order_by(ExtractedFact.created_at.desc()).offset(offset).limit(limit).all()
    docs = {d.id: d for d in db.query(Document).all()}
    items = []
    for f in rows:
        doc = docs.get(f.document_id)
        items.append(
            {
                "id": f.id,
                "entity": f.entity_name,
                "metric": f.field_name,
                "value": f.numeric_value if f.numeric_value is not None else f.value,
                "unit": f.unit,
                "fiscal_year": f.financial_year,
                "reporting_month": None,
                "measurement_type": None,
                "document_id": f.document_id,
                "document_name": doc.original_filename if doc else f.document_id,
                "page": f.page_number,
                "table_id": None,
                "table_title": None,
                "column_path": None,
                "source_location": f.source_location,
                "confidence": f.confidence_score,
                "status": f.status,
                "evidence_text": f.evidence_text,
                "data_type": "extracted_fact",
            }
        )
    return {"total": total, "items": items, "offset": offset, "limit": limit}


@router.get("/chunks")
def explore_chunks(
    document_id: Optional[str] = None,
    content_type: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    query = db.query(DocumentChunk).filter(DocumentChunk.is_active.is_(True))
    if document_id:
        query = query.filter(DocumentChunk.document_id == document_id)
    if content_type:
        query = query.filter(DocumentChunk.content_type == content_type)
    else:
        # Evidence exploration excludes structured_fact by default (use structured-facts endpoint)
        query = query.filter(DocumentChunk.content_type != "structured_fact")
    if q:
        query = query.filter(DocumentChunk.content.ilike(f"%{q}%"))
    total = query.count()
    rows = (
        query.order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": c.id,
            "document_id": c.document_id,
            "document_name": c.document_name,
            "page": c.page_number,
            "sheet_name": c.sheet_name,
            "source_location": c.source_location,
            "content_type": c.content_type,
            "evidence_text": c.content,
            "chunk_index": c.chunk_index,
        }
        for c in rows
    ]
    return {"total": total, "items": items, "offset": offset, "limit": limit}
