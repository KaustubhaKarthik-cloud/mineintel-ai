"""Semantic search API (Phase 4 retrieval + Phase 5 conflict metadata)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import AuthUser, require_permission
from app.config import get_settings
from app.database import get_db
from app.embeddings.provider import EmbeddingError
from app.rag.context_builder import build_rag_context
from app.retrieval.retriever import retrieve
from app.schemas import SearchRequest, SearchResponse, SearchResultItem
from app.validation.service import conflicts_for_documents

router = APIRouter()


@router.post("", response_model=SearchResponse)
def semantic_search(
    body: SearchRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("search")),
) -> SearchResponse:
    settings = get_settings()
    query = (body.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required.")
    if len(query) > settings.max_search_query_length:
        raise HTTPException(status_code=400, detail="Query is too long.")

    try:
        hits = retrieve(
            db,
            query,
            top_k=body.top_k,
            document_id=body.document_id,
        )
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Search failed. Please try again.") from exc

    doc_ids = list({h.chunk.document_id for h in hits})
    by_doc = conflicts_for_documents(db, doc_ids)

    results: list[SearchResultItem] = []
    conflict_map_for_context: dict[str, list[str]] = {}
    for h in hits:
        cids = [c.id for c in by_doc.get(h.chunk.document_id, [])]
        page_cids = [
            c.id
            for c in by_doc.get(h.chunk.document_id, [])
            if any(
                e.page_number == h.chunk.page_number
                for e in (c.evidence_items or [])
                if e.document_id == h.chunk.document_id
            )
        ]
        use_ids = page_cids or cids
        conflict_map_for_context[h.chunk.id] = use_ids
        results.append(
            SearchResultItem(
                text=h.chunk.content,
                score=round(h.score, 4),
                document=h.chunk.document_name,
                document_id=h.chunk.document_id,
                page=h.chunk.page_number,
                sheet_name=h.chunk.sheet_name,
                source_location=h.chunk.source_location,
                content_type=h.chunk.content_type or "document_evidence",
                document_version=h.chunk.document_version or 1,
                chunk_id=h.chunk.id,
                has_conflict=bool(use_ids),
                conflict_ids=use_ids,
            )
        )

    context = (
        build_rag_context(query, hits, conflict_ids_by_chunk=conflict_map_for_context, db=db)
        if body.include_context
        else None
    )
    return SearchResponse(query=query, results=results, context=context)
