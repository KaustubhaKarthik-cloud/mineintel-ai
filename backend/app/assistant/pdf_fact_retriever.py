"""Fact-level retrieval over header-first STRUCTURED_FACT chunks.

Complements semantic RAG: numerical questions prefer exact meta matches
(entity, metric, month, FY, measure) over embedding similarity alone.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.assistant.evidence_filter import evidence_compatible, entity_tokens
from app.assistant.query_router import QueryPlan
from app.assistant.rag_retriever import RagHit
from app.models import DocumentChunk

logger = logging.getLogger(__name__)


def _title_relevance(meta: dict, plan: QueryPlan) -> float:
    """Prefer facts whose table title clearly names the requested metric."""
    title = str(meta.get("table_title") or "").lower()
    metrics = [m.lower() for m in (plan.metrics or ([plan.metric] if plan.metric else [])) if m]
    score = 0.0
    if not title:
        return score
    if "coal" in metrics:
        if "coal" in title and "production" in title:
            score += 0.45
        elif "coal" in title:
            score += 0.2
        if "status" in title and "coal" not in title:
            score -= 0.3
        if any(x in title for x in ("dispatch", "supply", "washed", "coking")):
            score -= 0.35
    if "lignite" in metrics and "lignite" in title:
        score += 0.45
    if re.search(r"table\s+\d", title):
        score += 0.1
    if title.startswith("all figures") or "fig. in" in title:
        score -= 0.2
    return score


def retrieve_pdf_structured_facts(
    db: Session,
    plan: QueryPlan,
    *,
    document_id: Optional[str] = None,
    limit: int = 40,
) -> list[RagHit]:
    """Return STRUCTURED_FACT chunks compatible with the query plan."""
    if not plan or not plan.prefers_numeric:
        return []

    q = db.query(DocumentChunk).filter(
        DocumentChunk.is_active.is_(True),
        DocumentChunk.content_type == "structured_fact",
    )
    if document_id:
        q = q.filter(DocumentChunk.document_id == document_id)

    # Prefilter by entity token so large corpora are not truncated before match.
    tokens = entity_tokens(plan.entity)
    if tokens:
        # Match STRUCTURED_FACT entity=... field (word-boundary-ish via separators)
        q = q.filter(DocumentChunk.content.like(f"%entity={tokens[0]}%"))

    rows = q.limit(5000).all()
    out: list[RagHit] = []
    periods = list(plan.periods or [])

    for chunk in rows:
        meta = chunk.meta if isinstance(chunk.meta, dict) else {}
        text = chunk.content or ""
        title_boost = _title_relevance(meta, plan)
        if periods:
            ok_any = False
            best = None
            matched = None
            for p in periods:
                compat = evidence_compatible(
                    plan,
                    text,
                    require_entity=bool(plan.entity),
                    require_metric=bool(plan.metrics or plan.metric),
                    require_period=True,
                    active_periods=[p],
                    meta=meta,
                )
                if compat.ok and (best is None or compat.score > best.score):
                    ok_any = True
                    best = compat
                    matched = p
            if not ok_any or best is None:
                continue
            out.append(
                RagHit(
                    text=text,
                    score=0.92 + best.score * 0.01 + title_boost,
                    document_id=chunk.document_id,
                    document_name=chunk.document_name,
                    page=chunk.page_number,
                    sheet_name=chunk.sheet_name,
                    source_location=chunk.source_location,
                    chunk_id=chunk.id,
                    content_type=chunk.content_type or "structured_fact",
                    document_version=chunk.document_version or 1,
                    compat_score=best.score + title_boost,
                    compat_reasons=list(best.reasons) + (["title_relevance"] if title_boost > 0 else []),
                    matched_period=matched,
                )
            )
        else:
            compat = evidence_compatible(
                plan,
                text,
                require_entity=bool(plan.entity),
                require_metric=bool(plan.metrics or plan.metric),
                require_period=False,
                meta=meta,
            )
            if not compat.ok:
                continue
            out.append(
                RagHit(
                    text=text,
                    score=0.9 + compat.score * 0.01 + title_boost,
                    document_id=chunk.document_id,
                    document_name=chunk.document_name,
                    page=chunk.page_number,
                    sheet_name=chunk.sheet_name,
                    source_location=chunk.source_location,
                    chunk_id=chunk.id,
                    content_type=chunk.content_type or "structured_fact",
                    document_version=chunk.document_version or 1,
                    compat_score=compat.score + title_boost,
                    compat_reasons=list(compat.reasons) + (["title_relevance"] if title_boost > 0 else []),
                    matched_period=None,
                )
            )

    out.sort(key=lambda h: (h.score + h.compat_score), reverse=True)
    logger.info(
        "pdf_structured_facts entity=%s metrics=%s months=%s measures=%s kept=%d",
        plan.entity,
        plan.metrics or plan.metric,
        plan.reporting_months,
        plan.measure_types,
        len(out),
    )
    return out[:limit]
