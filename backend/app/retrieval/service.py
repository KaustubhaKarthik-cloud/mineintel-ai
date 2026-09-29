"""Index documents into the vector store (Phase 4)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.embeddings.provider import EmbeddingError, EmbeddingProvider, get_embedding_provider
from app.models import (
    AuditLog,
    Document,
    DocumentStatus,
    ExtractedFact,
    IndexStatus,
)
from app.retrieval.chunker import chunk_document_pages, chunk_verified_facts
from app.retrieval.structured_table import extract_facts_from_pdf_page, facts_to_chunk_drafts
from app.retrieval.vector_store import (
    deactivate_document_chunks,
    purge_inactive_document_chunks,
    upsert_chunks,
)
from pathlib import Path


class IndexingError(RuntimeError):
    pass


def index_document(
    db: Session,
    document_id: str,
    *,
    provider: EmbeddingProvider | None = None,
    include_verified_facts: bool | None = None,
) -> Document:
    doc = (
        db.query(Document)
        .options(joinedload(Document.pages))
        .filter(Document.id == document_id)
        .first()
    )
    if not doc:
        raise IndexingError("Document not found.")
    if doc.status in {DocumentStatus.FAILED.value, DocumentStatus.UPLOADED.value, DocumentStatus.PROCESSING.value}:
        raise IndexingError("Document must complete Phase 2 processing before indexing.")
    if not doc.pages:
        raise IndexingError("Document has no pages to index.")

    settings = get_settings()
    emb = provider or get_embedding_provider()
    use_facts = settings.index_verified_facts if include_verified_facts is None else include_verified_facts

    doc.index_status = IndexStatus.INDEXING.value
    doc.index_error = None
    db.commit()

    try:
        drafts = chunk_document_pages(doc, list(doc.pages))

        # Header-first PDF table facts (numeric grounding) — never invent from OCR blobs.
        pdf_path = Path(doc.file_path) if doc.file_path else None
        if pdf_path and pdf_path.is_file() and (
            (doc.file_type or "").lower() in {"pdf", "application/pdf"}
            or pdf_path.suffix.lower() == ".pdf"
        ):
            page_ids = {p.page_number: p.id for p in doc.pages}
            structured: list = []
            for p in doc.pages:
                structured.extend(extract_facts_from_pdf_page(pdf_path, p.page_number))
            struct_drafts = facts_to_chunk_drafts(
                structured,
                document_id=doc.id,
                document_name=doc.original_filename,
                document_version=doc.version or 1,
                page_id_by_number=page_ids,
                start_index=len(drafts),
            )
            drafts.extend(struct_drafts)

        if use_facts:
            facts = db.query(ExtractedFact).filter(ExtractedFact.document_id == doc.id).all()
            fact_drafts = chunk_verified_facts(doc, facts)
            base = len(drafts)
            for i, fd in enumerate(fact_drafts):
                fd.chunk_index = base + i
            drafts.extend(fact_drafts)

        if not drafts:
            raise IndexingError("No indexable text found in document.")

        # Deactivate previous active vectors (safe re-index), then purge inactive
        # so identical chunk ids can be re-inserted without UNIQUE conflicts.
        deactivate_document_chunks(db, doc.id)
        purge_inactive_document_chunks(db, doc.id)
        db.flush()

        # Batch embed
        texts = [d.text for d in drafts]
        vectors = emb.embed_texts(texts)
        if len(vectors) != len(texts):
            raise IndexingError("Embedding provider returned an unexpected number of vectors.")

        upsert_chunks(db, drafts, vectors, doc.id)

        doc.index_status = IndexStatus.INDEXED.value
        doc.embedding_completed = True
        doc.indexed_at = datetime.now(timezone.utc)
        doc.index_error = None
        db.add(
            AuditLog(
                action="VECTOR_INDEX",
                entity_type="document",
                entity_id=doc.id,
                actor="system",
                details={
                    "chunks": len(drafts),
                    "provider": emb.name,
                    "version": doc.version,
                },
            )
        )
        db.commit()
        db.refresh(doc)
        return doc
    except EmbeddingError as exc:
        db.rollback()
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.index_status = IndexStatus.INDEX_FAILED.value
            doc.index_error = str(exc)
            doc.embedding_completed = False
            db.commit()
        raise IndexingError(str(exc)) from exc
    except IndexingError:
        db.rollback()
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.index_status = IndexStatus.INDEX_FAILED.value
            doc.index_error = "Indexing failed."
            doc.embedding_completed = False
            db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.index_status = IndexStatus.INDEX_FAILED.value
            doc.index_error = "Indexing failed. Please try again."
            doc.embedding_completed = False
            db.commit()
        raise IndexingError("Indexing failed. Please try again.") from exc
