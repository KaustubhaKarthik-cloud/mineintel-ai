"""Citation helpers for assistant responses."""

from __future__ import annotations

from typing import Any, Optional

from app.assistant.rag_retriever import RagHit
from app.assistant.structured_retriever import StructuredFactHit
from app.models import ValidationConflict


def structured_to_dict(h: StructuredFactHit) -> dict[str, Any]:
    d = {
        "entity": h.entity,
        "metric": h.metric,
        "period": h.period,
        "value": h.value,
        "numeric_value": h.numeric_value,
        "unit": h.unit,
        "status": h.status,
        "source": h.document_name,
        "document_id": h.document_id,
        "page": h.page,
        "sheet_name": h.sheet_name,
        "evidence": h.evidence_text,
        "fact_id": h.fact_id,
        "confidence": h.confidence,
        "document_version": h.document_version,
    }
    if getattr(h, "seam_name", None):
        d["seam_name"] = h.seam_name
    if getattr(h, "borehole_id", None):
        d["borehole_id"] = h.borehole_id
    if getattr(h, "geological_formation", None):
        d["geological_formation"] = h.geological_formation
    if getattr(h, "seam_status", None):
        d["seam_status"] = h.seam_status
    if getattr(h, "value_min", None) is not None:
        d["value_min"] = h.value_min
    if getattr(h, "value_max", None) is not None:
        d["value_max"] = h.value_max
    return d


def rag_to_dict(h: RagHit) -> dict[str, Any]:
    d = {
        "document": h.document_name,
        "document_id": h.document_id,
        "page": h.page,
        "sheet_name": h.sheet_name,
        "evidence": h.text,
        "score": round(h.score, 4),
        "chunk_id": h.chunk_id,
        "content_type": h.content_type,
        "document_version": h.document_version,
    }
    if getattr(h, "matched_period", None):
        d["matched_period"] = h.matched_period
    if getattr(h, "compat_reasons", None):
        d["compat_reasons"] = h.compat_reasons
    return d


def conflict_to_dict(c: ValidationConflict) -> dict[str, Any]:
    return {
        "id": c.id,
        "conflict_type": c.conflict_type,
        "entity_name": c.entity_name,
        "field_name": c.field_name,
        "period": c.period,
        "status": c.status,
        "description": c.description,
        "evidence": [
            {
                "label": e.label,
                "document": e.document_name,
                "document_id": e.document_id,
                "page": e.page_number,
                "value": e.value,
                "unit": e.unit,
                "evidence": e.evidence_text,
                "is_calculated": e.is_calculated,
            }
            for e in (c.evidence_items or [])
        ],
    }


def build_chat_sources(
    structured: list[StructuredFactHit],
    rag: list[RagHit],
    conflicts: list[ValidationConflict],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_page: set[str] = set()

    def _fname_key(name: Optional[str]) -> str:
        import re

        return re.sub(r"[^a-z0-9]+", "", (name or "").lower())

    for h in structured:
        key = f"{h.document_id}:{h.page}:{h.fact_id}"
        page_key = f"{_fname_key(h.document_name)}:{h.page}:{_fname_key(h.value)}"
        if key in seen or page_key in seen_page:
            continue
        seen.add(key)
        seen_page.add(page_key)
        sources.append(
            {
                "document_id": h.document_id,
                "document_name": h.document_name,
                "snippet": (h.evidence_text or f"{h.metric}={h.value} {h.unit or ''}").strip(),
                "relevance": min(1.0, max(0.5, h.confidence)),
                "page": h.page,
                "sheet_name": h.sheet_name,
            }
        )
    for h in rag:
        key = f"rag:{h.chunk_id}"
        page_key = f"{_fname_key(h.document_name)}:{h.page}:{(h.text or '')[:80].lower()}"
        if key in seen or page_key in seen_page:
            continue
        seen.add(key)
        seen_page.add(page_key)
        sources.append(
            {
                "document_id": h.document_id,
                "document_name": h.document_name or h.document_id,
                "snippet": (h.text or "")[:240],
                "relevance": float(h.score),
                "page": h.page,
                "sheet_name": h.sheet_name,
            }
        )
    for c in conflicts:
        for e in c.evidence_items or []:
            if not e.document_id:
                continue
            key = f"c:{e.id}"
            page_key = f"{_fname_key(e.document_name)}:{e.page_number}"
            if key in seen or page_key in seen_page:
                continue
            seen.add(key)
            seen_page.add(page_key)
            sources.append(
                {
                    "document_id": e.document_id,
                    "document_name": e.document_name or e.document_id,
                    "snippet": (e.evidence_text or f"{e.value} {e.unit or ''}").strip(),
                    "relevance": 0.99,
                    "page": e.page_number,
                    "sheet_name": e.sheet_name,
                }
            )
    return sources
