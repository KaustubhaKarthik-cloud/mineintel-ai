"""Topic extraction from indexed chunks / pages (general keyword evidence)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentChunk, Topic, TopicEvidence
from app.topics.taxonomy import TOPIC_CUES, slugify


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _score_text(text: str) -> dict[str, tuple[float, list[str]]]:
    hay = (text or "").lower()
    if not hay.strip():
        return {}
    scored: dict[str, tuple[float, list[str]]] = {}
    for topic, cues in TOPIC_CUES.items():
        matched = [c for c in cues if c in hay]
        if not matched:
            continue
        # Longer cues weigh more
        score = min(1.0, 0.35 + 0.15 * len(matched) + 0.05 * sum(len(c) for c in matched) / 40.0)
        scored[topic] = (round(score, 3), matched)
    return scored


def extract_topics_from_corpus(db: Session, *, document_id: Optional[str] = None) -> dict:
    """Scan active chunks (or pages via chunks) and upsert topics + evidence links."""
    settings = get_settings()
    q = db.query(DocumentChunk).filter(DocumentChunk.is_active.is_(True))
    if document_id:
        q = q.filter(DocumentChunk.document_id == document_id)
    chunks = q.all()
    docs = {d.id: d for d in db.query(Document).all()}

    # Clear evidence for scoped re-extract
    if document_id:
        existing_ev = (
            db.query(TopicEvidence).filter(TopicEvidence.document_id == document_id).all()
        )
        for ev in existing_ev:
            db.delete(ev)
        db.flush()

    topic_rows: dict[str, Topic] = {t.name: t for t in db.query(Topic).all()}
    evidence_added = 0

    for chunk in chunks:
        text = chunk.content or ""
        scored = _score_text(text)
        if not scored:
            continue
        doc = docs.get(chunk.document_id)
        for topic_name, (conf, matched) in scored.items():
            if conf < 0.4:
                continue
            topic = topic_rows.get(topic_name)
            if not topic:
                topic = Topic(
                    name=topic_name,
                    slug=slugify(topic_name),
                    description=f"Corpus topic: {topic_name}",
                    keywords=list(TOPIC_CUES.get(topic_name, ())),
                    confidence=conf,
                    document_count=0,
                    chunk_count=0,
                )
                db.add(topic)
                db.flush()
                topic_rows[topic_name] = topic
            # Avoid duplicate evidence for same chunk+topic
            dup = (
                db.query(TopicEvidence)
                .filter(
                    TopicEvidence.topic_id == topic.id,
                    TopicEvidence.chunk_id == chunk.id,
                )
                .first()
            )
            if dup:
                continue
            snippet = text.strip()
            if len(snippet) > 600:
                snippet = snippet[:600] + "…"
            db.add(
                TopicEvidence(
                    topic_id=topic.id,
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    document_page_id=chunk.document_page_id,
                    page_number=chunk.page_number,
                    sheet_name=chunk.sheet_name,
                    document_name=chunk.document_name
                    or (doc.original_filename if doc else None),
                    evidence_text=snippet,
                    confidence=conf,
                    matched_keywords=matched,
                )
            )
            evidence_added += 1

    db.flush()
    # Refresh counts
    for topic in topic_rows.values():
        evs = db.query(TopicEvidence).filter(TopicEvidence.topic_id == topic.id).all()
        doc_ids = {e.document_id for e in evs}
        topic.document_count = len(doc_ids)
        topic.chunk_count = len(evs)
        topic.last_extracted_at = _utcnow()
        if evs:
            topic.confidence = round(sum(e.confidence or 0 for e in evs) / len(evs), 3)
        # Drop empty topics when re-extracting whole corpus
        if not document_id and topic.chunk_count < settings.topic_min_hits:
            pass  # keep taxonomy row even if sparse

    db.commit()
    return {
        "topics": len(topic_rows),
        "evidence_added": evidence_added,
        "chunks_scanned": len(chunks),
    }
