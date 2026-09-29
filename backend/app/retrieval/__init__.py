"""Phase 4 retrieval package."""

from app.retrieval.service import IndexingError, index_document
from app.retrieval.retriever import retrieve

__all__ = ["index_document", "IndexingError", "retrieve"]
