"""Verified structured facts from indexed STRUCTURED_FACT chunks.

These are the header-first table extractions values (numeric truth),
distinct from AI ExtractedFact rows. Analytics and Data Exploration
prefer this source when present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.assistant.structured_retriever import StructuredFactHit, _entity_soft_match
from app.models import Document, DocumentChunk
from app.validation.rules import normalize_entity, normalize_field, normalize_period


@dataclass
class IndexFact:
    """Normalized row from a structured_fact chunk meta."""

    entity: str
    metric: str
    reporting_month: Optional[str]
    fiscal_year: Optional[str]
    measurement_type: Optional[str]
    value: float
    unit: Optional[str]
    document_id: str
    document_name: str
    page: Optional[int]
    table_id: Optional[str]
    table_title: Optional[str]
    column_path: Optional[str]
    chunk_id: str
    confidence: float
    evidence_text: Optional[str]

    @property
    def period(self) -> Optional[str]:
        """Primary period key for year-wise charts (fiscal year)."""
        return normalize_period(self.fiscal_year) if self.fiscal_year else None


def _chunk_to_index_fact(chunk: DocumentChunk) -> Optional[IndexFact]:
    meta = chunk.meta if isinstance(chunk.meta, dict) else {}
    if not meta.get("structured_fact") and chunk.content_type != "structured_fact":
        return None
    try:
        value = float(meta.get("value"))
    except (TypeError, ValueError):
        return None
    entity = str(meta.get("entity") or "").strip()
    metric = normalize_field(str(meta.get("metric") or "")) or str(meta.get("metric") or "").strip()
    if not entity or not metric:
        return None
    fy_raw = meta.get("fiscal_year") or ""
    month = meta.get("reporting_month")
    if isinstance(month, str):
        month = month.strip() or None
    measure = meta.get("measurement_type")
    if isinstance(measure, str):
        measure = measure.strip().lower() or None
    conf = meta.get("confidence")
    try:
        confidence = float(conf) if conf is not None else 0.9
    except (TypeError, ValueError):
        confidence = 0.9
    return IndexFact(
        entity=entity,
        metric=metric,
        reporting_month=month,
        fiscal_year=normalize_period(str(fy_raw)) if fy_raw else None,
        measurement_type=measure,
        value=value,
        unit=(str(meta.get("unit")).strip() if meta.get("unit") else None),
        document_id=chunk.document_id,
        document_name=chunk.document_name or chunk.document_id,
        page=chunk.page_number if chunk.page_number is not None else meta.get("page"),
        table_id=str(meta.get("table_id")) if meta.get("table_id") else None,
        table_title=str(meta.get("table_title")) if meta.get("table_title") else None,
        column_path=str(meta.get("column_path")) if meta.get("column_path") else None,
        chunk_id=chunk.id,
        confidence=confidence,
        evidence_text=chunk.content,
    )


def list_index_facts(
    db: Session,
    *,
    document_ids: Optional[list[str]] = None,
    entity: Optional[str] = None,
    metric: Optional[str] = None,
    fiscal_year: Optional[str] = None,
    reporting_month: Optional[str] = None,
    measurement_type: Optional[str] = None,
    limit: int = 5000,
) -> list[IndexFact]:
    q = db.query(DocumentChunk).filter(
        DocumentChunk.is_active.is_(True),
        DocumentChunk.content_type == "structured_fact",
    )
    if document_ids:
        q = q.filter(DocumentChunk.document_id.in_(document_ids))
    rows = q.limit(limit).all()

    want_metric = normalize_field(metric) if metric else None
    want_fy = normalize_period(fiscal_year) if fiscal_year else None
    want_month = (reporting_month or "").strip().lower() or None
    want_measure = (measurement_type or "").strip().lower() or None

    out: list[IndexFact] = []
    for chunk in rows:
        fact = _chunk_to_index_fact(chunk)
        if not fact:
            continue
        if want_metric and fact.metric != want_metric:
            continue
        if entity and not _entity_soft_match(entity, fact.entity):
            continue
        if want_fy and fact.fiscal_year != want_fy:
            continue
        if want_month and (fact.reporting_month or "").lower() != want_month:
            continue
        if want_measure and (fact.measurement_type or "") != want_measure:
            continue
        out.append(fact)
    return out


def _is_plausible_entity(name: str) -> bool:
    """Drop OCR noise that is not an organization/row label for analytics filters."""
    s = (name or "").strip()
    if len(s) < 2 or len(s) > 80:
        return False
    if s.startswith("%") or s.startswith("("):
        return False
    if re.fullmatch(r"[\d.,\s/-]+", s):
        return False
    # Pure unit / footnote fragments
    low = s.lower()
    if low in {"mt", "te", "na", "n/a", "total", "others", "sub total", "sub-total"}:
        return False
    return True


def index_fact_dimensions(
    db: Session,
    *,
    document_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    facts = list_index_facts(db, document_ids=document_ids, limit=10000)
    entities: set[str] = set()
    metrics: set[str] = set()
    periods: set[str] = set()
    months: set[str] = set()
    measures: set[str] = set()
    for f in facts:
        if _is_plausible_entity(f.entity):
            entities.add(f.entity)
        metrics.add(f.metric)
        if f.fiscal_year:
            periods.add(f.fiscal_year)
        if f.reporting_month:
            months.add(f.reporting_month)
        if f.measurement_type:
            measures.add(f.measurement_type)
    return {
        "entities": sorted(entities, key=lambda x: x.lower()),
        "metrics": sorted(metrics),
        "periods": sorted(periods),
        "reporting_months": sorted(months, key=lambda x: x.lower()),
        "measurement_types": sorted(measures),
    }


def index_facts_as_hits(facts: list[IndexFact]) -> list[StructuredFactHit]:
    """Adapt IndexFact → StructuredFactHit for existing analytics aggregators."""
    hits: list[StructuredFactHit] = []
    for f in facts:
        hits.append(
            StructuredFactHit(
                entity=f.entity,
                metric=f.metric,
                period=f.period,
                value=str(f.value),
                numeric_value=f.value,
                unit=f.unit,
                status="verified_index",
                document_id=f.document_id,
                document_name=f.document_name,
                document_version=1,
                page=f.page,
                sheet_name=None,
                evidence_text=f.evidence_text,
                fact_id=f.chunk_id,
                confidence=f.confidence,
            )
        )
    return hits


def list_analytics_documents(db: Session) -> list[dict[str, Any]]:
    """Documents that have structured facts and/or verified extracted facts."""
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
    chunk_doc_ids = {
        r[0]
        for r in db.query(DocumentChunk.document_id)
        .filter(
            DocumentChunk.is_active.is_(True),
            DocumentChunk.content_type == "structured_fact",
        )
        .distinct()
        .all()
    }
    out = []
    for d in docs:
        fact_count = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.document_id == d.id,
                DocumentChunk.is_active.is_(True),
                DocumentChunk.content_type == "structured_fact",
            )
            .count()
        )
        out.append(
            {
                "id": d.id,
                "name": d.original_filename or d.filename,
                "file_type": d.file_type,
                "status": d.status,
                "page_count": d.page_count,
                "index_status": d.index_status,
                "structured_fact_count": fact_count,
                "has_structured_data": d.id in chunk_doc_ids or fact_count > 0,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
        )
    return out
