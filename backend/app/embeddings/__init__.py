"""Phase 4 embeddings package."""

from app.embeddings.provider import EmbeddingError, EmbeddingProvider, get_embedding_provider

__all__ = ["EmbeddingError", "EmbeddingProvider", "get_embedding_provider"]
