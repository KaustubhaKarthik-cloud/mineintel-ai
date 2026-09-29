"""Topic listing, detail, and grounded summarization."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.assistant.providers import LLMProvider, MockLLMProvider, get_assistant_llm
from app.config import get_settings
from app.models import Topic, TopicEvidence
from app.retrieval.retriever import retrieve
from app.topics.extractor import extract_topics_from_corpus
from app.topics.taxonomy import TOPIC_CUES


def list_topics(db: Session) -> list[dict[str, Any]]:
    rows = db.query(Topic).order_by(Topic.name.asc()).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "description": t.description,
            "document_count": t.document_count or 0,
            "chunk_count": t.chunk_count or 0,
            "keywords": t.keywords or list(TOPIC_CUES.get(t.name, ())),
            "confidence": t.confidence,
            "has_summary": bool(t.summary),
        }
        for t in rows
    ]


def get_topic(db: Session, topic_id: str) -> Optional[dict[str, Any]]:
    t = db.query(Topic).filter(Topic.id == topic_id).first()
    if not t:
        t = db.query(Topic).filter(Topic.slug == topic_id).first()
    if not t:
        return None
    evidence = (
        db.query(TopicEvidence)
        .filter(TopicEvidence.topic_id == t.id)
        .order_by(TopicEvidence.confidence.desc())
        .limit(40)
        .all()
    )
    return {
        "id": t.id,
        "name": t.name,
        "slug": t.slug,
        "description": t.description,
        "document_count": t.document_count or 0,
        "chunk_count": t.chunk_count or 0,
        "keywords": t.keywords or list(TOPIC_CUES.get(t.name, ())),
        "confidence": t.confidence,
        "summary": t.summary,
        "summary_citations": t.summary_citations or [],
        "evidence": [
            {
                "id": e.id,
                "document_id": e.document_id,
                "document_name": e.document_name,
                "chunk_id": e.chunk_id,
                "page": e.page_number,
                "sheet_name": e.sheet_name,
                "evidence_text": e.evidence_text,
                "confidence": e.confidence,
                "matched_keywords": e.matched_keywords or [],
            }
            for e in evidence
        ],
    }


def _build_summary_from_evidence(topic_name: str, snippets: list[dict[str, Any]]) -> str:
    if not snippets:
        return (
            f"I couldn't find sufficient verified evidence to summarize the topic "
            f"'{topic_name}'."
        )
    lines = [f"Topic summary for {topic_name} (from retrieved document evidence):", ""]
    for s in snippets[:6]:
        loc = s.get("document_name") or s.get("document_id") or "document"
        page = s.get("page")
        cite = f"{loc}" + (f", Page {page}" if page else "")
        text = (s.get("evidence_text") or "").strip()
        if len(text) > 280:
            text = text[:280] + "…"
        lines.append(f"- [{cite}] {text}")
    lines.append("")
    lines.append("No numbers outside the cited evidence were introduced.")
    return "\n".join(lines)


def summarize_topic(
    db: Session,
    topic_id: str,
    *,
    provider: Optional[LLMProvider] = None,
    refresh_retrieval: bool = True,
) -> dict[str, Any]:
    detail = get_topic(db, topic_id)
    if not detail:
        return {"error": "Topic not found", "insufficient": True}

    settings = get_settings()
    snippets: list[dict[str, Any]] = list(detail.get("evidence") or [])

    # Supplement with RAG if sparse
    if refresh_retrieval and len(snippets) < 2:
        hits = retrieve(db, detail["name"], top_k=settings.topic_summary_top_k)
        for h in hits:
            c = h.chunk
            snippets.append(
                {
                    "document_id": c.document_id,
                    "document_name": c.document_name,
                    "page": c.page_number,
                    "sheet_name": c.sheet_name,
                    "evidence_text": c.content,
                    "confidence": h.score,
                    "chunk_id": c.id,
                }
            )

    if not snippets:
        summary = _build_summary_from_evidence(detail["name"], [])
        return {
            **detail,
            "summary": summary,
            "summary_citations": [],
            "insufficient": True,
            "llm_provider": "none",
        }

    # Dedupe by chunk/page text prefix
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for s in snippets:
        key = f"{s.get('document_id')}|{s.get('page')}|{(s.get('evidence_text') or '')[:80]}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    snippets = unique[: settings.topic_summary_top_k]

    citations = [
        {
            "document_id": s.get("document_id"),
            "document_name": s.get("document_name"),
            "page": s.get("page"),
            "sheet_name": s.get("sheet_name"),
            "snippet": (s.get("evidence_text") or "")[:240],
        }
        for s in snippets
    ]

    evidence_block = "\n\n".join(
        f"Source: {c['document_name']} page={c['page']}\n{c['snippet']}" for c in citations
    )
    system = (
        "You are MineIntel topic summarizer. Use ONLY the provided evidence. "
        "Do not invent numbers, mines, or facts. If evidence is thin, say so. "
        "Keep the summary concise (3-6 sentences) and mention document/page when citing figures."
    )
    user = f"Topic: {detail['name']}\n\nEvidence:\n{evidence_block}\n\nWrite a grounded summary."

    llm = provider or get_assistant_llm()
    provider_name = getattr(llm, "name", "unknown")
    if isinstance(llm, MockLLMProvider):
        summary = _build_summary_from_evidence(detail["name"], snippets)
    else:
        try:
            summary = llm.generate(system, user)
            if not summary or not str(summary).strip():
                summary = _build_summary_from_evidence(detail["name"], snippets)
        except Exception:  # noqa: BLE001
            summary = _build_summary_from_evidence(detail["name"], snippets)
            provider_name = f"{provider_name}_fallback_mock"

    # Persist on topic row
    topic = db.query(Topic).filter(Topic.id == detail["id"]).first()
    if topic:
        topic.summary = summary
        topic.summary_citations = citations
        db.commit()

    return {
        **detail,
        "summary": summary,
        "summary_citations": citations,
        "insufficient": False,
        "llm_provider": provider_name,
    }


def ensure_topics(db: Session) -> dict:
    """Run corpus extraction if no topics exist yet."""
    count = db.query(Topic).count()
    if count == 0:
        return extract_topics_from_corpus(db)
    return {"topics": count, "evidence_added": 0, "chunks_scanned": 0, "skipped": True}
