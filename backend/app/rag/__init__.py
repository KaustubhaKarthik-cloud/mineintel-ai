"""RAG helpers — retrieval context only (Phase 4). Answer generation comes later."""

from app.rag.context_builder import build_rag_context, build_rag_context_payload

__all__ = ["build_rag_context", "build_rag_context_payload"]
