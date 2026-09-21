"""Vector storage abstraction — SQLite JSON + cosine; pgvector-ready interface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from app.models import DocumentChunk
from app.retrieval.chunker import ChunkDraft


@dataclass
class SearchHit:
    chunk: DocumentChunk
    score: float


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    if va.shape != vb.shape or va.size == 0:
        return 0.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def deactivate_document_chunks(db: Session, document_id: str) -> int:
    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id, DocumentChunk.is_active.is_(True))
        .all()
    )
    for row in rows:
        row.is_active = False
    return len(rows)


def purge_inactive_document_chunks(db: Session, document_id: str) -> int:
    """Remove inactive chunks so re-index can insert fresh ids cleanly."""
    q = db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document_id,
        DocumentChunk.is_active.is_(False),
    )
    n = q.count()
    q.delete(synchronize_session=False)
    return n


def upsert_chunks(
    db: Session,
    drafts: list[ChunkDraft],
    embeddings: list[list[float]],
    document_id: str,
) -> list[DocumentChunk]:
    assert len(drafts) == len(embeddings)
    # Last-wins dedupe — identical structured facts / chunk keys must not double-insert.
    merged: dict[str, tuple[ChunkDraft, list[float]]] = {}
    for draft, emb in zip(drafts, embeddings):
        merged[draft.chunk_id] = (draft, emb)

    stored: list[DocumentChunk] = []
    now = datetime.now(timezone.utc)
    pending: dict[str, DocumentChunk] = {}
    for chunk_id, (draft, emb) in merged.items():
        existing = db.query(DocumentChunk).filter(DocumentChunk.id == chunk_id).first()
        if existing is None:
            existing = pending.get(chunk_id)
        if existing:
            existing.content = draft.text
            existing.embedding_json = emb
            existing.is_active = True
            existing.chunk_index = draft.chunk_index
            existing.document_page_id = draft.document_page_id
            existing.page_number = draft.page_number
            existing.sheet_name = draft.sheet_name
            existing.source_type = draft.source_type
            existing.source_location = draft.source_location
            existing.document_name = draft.document_name
            existing.document_version = draft.document_version
            existing.content_type = draft.content_type
            existing.token_count = draft.token_count
            existing.meta = draft.meta
            existing.updated_at = now
            stored.append(existing)
        else:
            row = DocumentChunk(
                id=draft.chunk_id,
                document_id=document_id,
                document_page_id=draft.document_page_id,
                chunk_index=draft.chunk_index,
                content=draft.text,
                content_type=draft.content_type,
                page_number=draft.page_number,
                sheet_name=draft.sheet_name,
                source_type=draft.source_type,
                source_location=draft.source_location,
                document_name=draft.document_name,
                document_version=draft.document_version,
                token_count=draft.token_count,
                embedding_json=emb,
                is_active=True,
                meta=draft.meta,
            )
            db.add(row)
            pending[chunk_id] = row
            stored.append(row)
    db.flush()
    return stored


def search_similar(
    db: Session,
    query_embedding: list[float],
    *,
    top_k: int,
    min_score: float,
    document_id: Optional[str] = None,
    document_ids: Optional[list[str]] = None,
    active_only: bool = True,
) -> list[SearchHit]:
    q = db.query(DocumentChunk)
    if active_only:
        q = q.filter(DocumentChunk.is_active.is_(True))
    if document_ids:
        q = q.filter(DocumentChunk.document_id.in_(list(document_ids)))
    elif document_id:
        q = q.filter(DocumentChunk.document_id == document_id)
    rows = q.filter(DocumentChunk.embedding_json.isnot(None)).all()
    hits: list[SearchHit] = []
    for row in rows:
        if not row.embedding_json:
            continue
        score = cosine_similarity(query_embedding, row.embedding_json)
        if score >= min_score:
            hits.append(SearchHit(chunk=row, score=score))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]
