"""Thin wrapper over Phase 4 semantic retrieval for the assistant.

Applies generic entity/metric/period compatibility filtering so semantically
similar but factually mismatched chunks are not passed to the LLM as evidence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.assistant.evidence_filter import evidence_compatible
from app.assistant.query_router import QueryPlan
from app.config import get_settings
from app.retrieval.retriever import retrieve
from app.retrieval.vector_store import SearchHit

logger = logging.getLogger(__name__)


@dataclass
class RagHit:
    text: str
    score: float
    document_id: str
    document_name: Optional[str]
    page: Optional[int]
    sheet_name: Optional[str]
    source_location: Optional[str]
    chunk_id: str
    content_type: str
    document_version: int
    compat_score: float = 0.0
    compat_reasons: Optional[list[str]] = None
    matched_period: Optional[str] = None


def _to_rag_hit(
    h: SearchHit,
    *,
    compat_score: float = 0.0,
    compat_reasons: Optional[list[str]] = None,
    matched_period: Optional[str] = None,
) -> RagHit:
    c = h.chunk
    return RagHit(
        text=c.content,
        score=h.score,
        document_id=c.document_id,
        document_name=c.document_name,
        page=c.page_number,
        sheet_name=c.sheet_name,
        source_location=c.source_location,
        chunk_id=c.id,
        content_type=c.content_type or "document_evidence",
        document_version=c.document_version or 1,
        compat_score=compat_score,
        compat_reasons=compat_reasons,
        matched_period=matched_period,
    )


def _filter_hits(
    hits: list[SearchHit],
    plan: Optional[QueryPlan],
    *,
    active_periods: Optional[list[str]] = None,
    require_period: bool = False,
) -> list[RagHit]:
    if plan is None:
        return [_to_rag_hit(h) for h in hits]

    # Numerical factual queries: require entity + metric compatibility.
    strict = bool(plan.prefers_numeric or plan.entity or plan.metrics)
    out: list[RagHit] = []
    for h in hits:
        text = h.chunk.content or ""
        meta = getattr(h.chunk, "meta", None) or {}
        compat = evidence_compatible(
            plan,
            text,
            require_entity=strict and bool(plan.entity),
            require_metric=strict and bool(plan.metrics or plan.metric),
            require_period=require_period,
            active_periods=active_periods,
            meta=meta if isinstance(meta, dict) else None,
        )
        logger.debug(
            "rag_compat query=%r doc=%s page=%s score=%.3f ok=%s reasons=%s entity=%s metrics=%s periods=%s",
            (plan.raw_question or "")[:120],
            h.chunk.document_name,
            h.chunk.page_number,
            h.score,
            compat.ok,
            compat.reasons,
            plan.entity,
            plan.metrics or plan.metric,
            active_periods if active_periods is not None else plan.periods,
        )
        if not compat.ok:
            continue
        matched_period = None
        periods = active_periods if active_periods is not None else plan.periods
        if periods and len(periods) == 1:
            matched_period = periods[0]
        out.append(
            _to_rag_hit(
                h,
                compat_score=compat.score,
                compat_reasons=list(compat.reasons),
                matched_period=matched_period,
            )
        )
    return out


def _period_query(base: str, period: str) -> str:
    """Augment query with an explicit period cue for independent retrieval."""
    if period.lower() in base.lower():
        return base
    return f"{base} {period}"


def _focus_evidence_for_entity(text: str, entity: Optional[str], plan: Optional[QueryPlan] = None) -> str:
    """Keep reconstructed rows for the asked entity / month / measure."""
    if not text or not entity:
        return text
    low = text.lower()
    if "reconstructed from source" not in low:
        return text
    tokens = [t for t in re.findall(r"[a-z0-9]{2,}", entity.lower()) if t not in {"the", "and", "of"}]
    if not tokens:
        return text
    title = ""
    body = text
    if ":" in text[:160]:
        title, body = text.split(":", 1)
        title = title.strip() + ":"

    # Structured rows: "... | reporting_period=Month | measure=during | FY25=1.2 MT | FY24=3.4 MT."
    rows = re.findall(
        r"((?:[A-Z][^|]{0,80}?)\|\s*reporting_period=\w+\s*\|\s*measure=\w+\s*\|\s*"
        r"FY25=[\d.]+\s*MT\s*\|\s*FY24=[\d.]+\s*MT\.)",
        body,
        re.I,
    )
    if not rows:
        # Legacy fallback
        ent_pat = r"\s+".join(re.escape(t) for t in tokens)
        m = re.search(
            rf"({ent_pat}\s+(?:coal|lignite|overburden|production)\b.*?)(?=(?:[A-Z][A-Za-z .&/-]{{1,40}}\s+(?:coal|lignite|overburden)\s+production\b)|$)",
            body,
            re.I | re.S,
        )
        if not m:
            return text
        focused = m.group(1).strip()
        if not focused.endswith("."):
            focused += "."
        return f"{title} {focused}".strip() if title else focused

    months = list((plan.reporting_months if plan else None) or [])
    measures = list((plan.measure_types if plan else None) or [])
    keep: list[str] = []
    for row in rows:
        rl = row.lower()
        if not all(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", rl) for t in tokens):
            continue
        if months and not any(m.lower() in rl for m in months):
            continue
        if measures and not any(f"measure={m}" in rl.replace(" ", "") for m in measures):
            continue
        keep.append(row.strip())
    if not keep:
        return text
    focused = " ".join(keep)
    return f"{title} {focused}".strip() if title else focused


def _prefer_structured_facts(hits: list[RagHit], plan: Optional[QueryPlan]) -> list[RagHit]:
    """Prefer structured_fact chunks over free-text / legacy reconstructed blobs."""
    if not hits:
        return hits
    structured = [h for h in hits if h.content_type == "structured_fact" or "STRUCTURED_FACT" in (h.text or "")]
    if structured and plan and plan.prefers_numeric:
        # Drop free-text competitors when structured facts already cover the ask
        ranked = sorted(structured, key=lambda x: (x.score + x.compat_score), reverse=True)
        return ranked
    # Legacy reconstructed preference when no structured facts present
    return _prefer_reconstructed(hits, plan)


def _prefer_reconstructed(hits: list[RagHit], plan: Optional[QueryPlan]) -> list[RagHit]:
    """Prefer reconstructed table evidence over raw OCR scrapes of the same page."""
    if not hits:
        return hits
    recon_keys = {
        (h.document_id, h.page)
        for h in hits
        if "reconstructed from source" in (h.text or "").lower()
    }
    out: list[RagHit] = []
    for h in hits:
        key = (h.document_id, h.page)
        is_recon = "reconstructed from source" in (h.text or "").lower()
        if key in recon_keys and not is_recon:
            continue
        text = h.text
        if plan and plan.entity and is_recon:
            text = _focus_evidence_for_entity(text, plan.entity, plan)
        if text != h.text:
            h = RagHit(
                text=text,
                score=h.score + 0.08,
                document_id=h.document_id,
                document_name=h.document_name,
                page=h.page,
                sheet_name=h.sheet_name,
                source_location=h.source_location,
                chunk_id=h.chunk_id,
                content_type=h.content_type,
                document_version=h.document_version,
                compat_score=h.compat_score + 0.15,
                compat_reasons=list(h.compat_reasons or []) + ["reconstructed_focus"],
                matched_period=h.matched_period,
            )
        elif is_recon:
            h = RagHit(
                text=h.text,
                score=h.score + 0.05,
                document_id=h.document_id,
                document_name=h.document_name,
                page=h.page,
                sheet_name=h.sheet_name,
                source_location=h.source_location,
                chunk_id=h.chunk_id,
                content_type=h.content_type,
                document_version=h.document_version,
                compat_score=h.compat_score + 0.1,
                compat_reasons=list(h.compat_reasons or []) + ["reconstructed_table"],
                matched_period=h.matched_period,
            )
        out.append(h)
    out.sort(key=lambda x: (x.score + x.compat_score), reverse=True)
    return out


def retrieve_rag_evidence(
    db: Session,
    query: str,
    *,
    top_k: Optional[int] = None,
    document_id: Optional[str] = None,
    plan: Optional[QueryPlan] = None,
) -> list[RagHit]:
    settings = get_settings()
    k = top_k or settings.assistant_rag_top_k
    # Pull a wider pool so compatibility filtering still has candidates.
    pool_k = max(k * 4, 12)

    # Fact-first path for numerical queries with structured PDF facts.
    fact_hits: list[RagHit] = []
    if plan and plan.prefers_numeric:
        from app.assistant.pdf_fact_retriever import retrieve_pdf_structured_facts

        fact_hits = retrieve_pdf_structured_facts(
            db, plan, document_id=document_id, limit=max(k * 3, 12)
        )

    periods = list(plan.periods) if plan and plan.periods else []

    # Multi-period numerical queries: retrieve per period, then merge.
    if plan and plan.prefers_numeric and len(periods) > 1:
        merged: dict[str, RagHit] = {}
        for h in fact_hits:
            merged[h.chunk_id] = h
        for period in periods:
            q = _period_query(query, period)
            raw = retrieve(db, q, top_k=pool_k, document_id=document_id)
            filtered = _filter_hits(
                raw,
                plan,
                active_periods=[period],
                require_period=True,
            )
            for hit in filtered:
                hit.matched_period = period
                prev = merged.get(hit.chunk_id)
                if prev is None or (hit.score + hit.compat_score) > (
                    prev.score + prev.compat_score
                ):
                    merged[hit.chunk_id] = hit
        # Also run a month-scoped retrieve when reporting month requested
        if plan.reporting_months:
            mq = f"{query} {plan.reporting_months[0]}"
            raw = retrieve(db, mq, top_k=pool_k, document_id=document_id)
            for hit in _filter_hits(raw, plan, active_periods=None, require_period=False):
                prev = merged.get(hit.chunk_id)
                if prev is None or (hit.score + hit.compat_score) > (
                    prev.score + prev.compat_score
                ):
                    merged[hit.chunk_id] = hit
        ranked = sorted(
            merged.values(),
            key=lambda h: (h.score + h.compat_score),
            reverse=True,
        )
        ranked = _prefer_structured_facts(ranked, plan)
        logger.info(
            "rag_multi_period query=%r periods=%s kept=%d facts=%d",
            query[:120],
            periods,
            len(ranked),
            len(fact_hits),
        )
        return ranked[:k]

    raw_hits: list[SearchHit] = retrieve(
        db, query, top_k=pool_k, document_id=document_id
    )
    require_period = bool(
        plan
        and plan.prefers_numeric
        and plan.entity
        and (plan.metrics or plan.metric)
        and len(periods) == 1
    )
    filtered = _filter_hits(
        raw_hits,
        plan,
        active_periods=periods or None,
        require_period=require_period,
    )
    # Merge fact-first hits
    by_id = {h.chunk_id: h for h in fact_hits}
    for h in filtered:
        prev = by_id.get(h.chunk_id)
        if prev is None or (h.score + h.compat_score) > (prev.score + prev.compat_score):
            by_id[h.chunk_id] = h
    filtered = sorted(by_id.values(), key=lambda h: (h.score + h.compat_score), reverse=True)
    filtered = _prefer_structured_facts(filtered, plan)
    logger.info(
        "rag_filtered query=%r entity=%s metrics=%s periods=%s raw=%d kept=%d facts=%d",
        query[:120],
        plan.entity if plan else None,
        (plan.metrics or plan.metric) if plan else None,
        periods,
        len(raw_hits),
        len(filtered),
        len(fact_hits),
    )
    return filtered[:k]
