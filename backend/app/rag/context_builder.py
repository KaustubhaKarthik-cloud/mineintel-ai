"""Build structured RAG context from retrieved chunks (no LLM answering yet)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models import ConflictStatus, ValidationConflict
from app.retrieval.vector_store import SearchHit


def build_rag_context(
    query: str,
    hits: list[SearchHit],
    *,
    conflict_ids_by_chunk: Optional[dict[str, list[str]]] = None,
    db: Optional[Session] = None,
) -> str:
    if not hits:
        return f"QUERY:\n{query}\n\nCONTEXT:\n(No relevant evidence retrieved.)\n"

    conflict_cache: dict[str, ValidationConflict] = {}
    if db and conflict_ids_by_chunk:
        all_ids = {cid for ids in conflict_ids_by_chunk.values() for cid in ids}
        if all_ids:
            rows = db.query(ValidationConflict).filter(ValidationConflict.id.in_(all_ids)).all()
            conflict_cache = {r.id: r for r in rows}

    blocks = [f"QUERY:\n{query}\n", "CONTEXT\n"]
    for i, hit in enumerate(hits, start=1):
        c = hit.chunk
        loc = (
            f"Sheet: {c.sheet_name}"
            if c.sheet_name
            else (f"Page: {c.page_number}" if c.page_number is not None else "Source: n/a")
        )
        cids = (conflict_ids_by_chunk or {}).get(c.id, [])
        open_conflicts = [
            conflict_cache[cid]
            for cid in cids
            if cid in conflict_cache
            and conflict_cache[cid].status
            not in {ConflictStatus.DISMISSED.value, ConflictStatus.RESOLVED.value}
        ]
        if open_conflicts:
            tag = "[CONFLICT]"
            conflict_lines = []
            for conf in open_conflicts:
                conflict_lines.append(
                    f"Conflict {conf.id}: {conf.field_name} / {conf.entity_name} / {conf.period} "
                    f"— status {conf.status}. Human verification required. Do not pick a side."
                )
            extra = "\n".join(conflict_lines)
        else:
            tag = "[VERIFIED]" if (c.content_type or "") == "verified_fact" else "[EVIDENCE]"
            extra = ""

        blocks.append(
            f"{tag} [Source {i}]\n"
            f"Document: {c.document_name or c.document_id}\n"
            f"{loc}\n"
            f"Content type: {c.content_type}\n"
            f"Similarity: {hit.score:.3f}\n"
            f"Evidence:\n{c.content}\n"
            + (f"{extra}\n" if extra else "")
        )
    return "\n".join(blocks)


def build_rag_context_payload(query: str, hits: list[SearchHit]) -> dict:
    return {
        "query": query,
        "context_text": build_rag_context(query, hits),
        "sources": [
            {
                "rank": i + 1,
                "document_id": h.chunk.document_id,
                "document_name": h.chunk.document_name,
                "page_number": h.chunk.page_number,
                "sheet_name": h.chunk.sheet_name,
                "source_location": h.chunk.source_location,
                "content_type": h.chunk.content_type,
                "score": round(h.score, 4),
                "text": h.chunk.content,
                "document_version": h.chunk.document_version,
            }
            for i, h in enumerate(hits)
        ],
    }
