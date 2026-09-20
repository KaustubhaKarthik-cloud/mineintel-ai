"""System status for Settings page — no secrets exposed."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.assistant.providers import probe_local_llm
from app.auth.deps import ROLE_PERMISSIONS, AuthUser, get_current_user, require_permission
from app.config import get_settings
from app.database import get_db
from app.models import AuditLog, Document, DocumentChunk, ExtractedFact, Report
from app.utils.files import documents_root

router = APIRouter()


@router.get("/status")
def system_status(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    settings = get_settings()
    docs_root = documents_root()
    storage_ok = docs_root.exists()
    doc_count = db.query(func.count(Document.id)).scalar() or 0
    fact_count = db.query(func.count(ExtractedFact.id)).scalar() or 0
    chunk_count = (
        db.query(func.count(DocumentChunk.id)).filter(DocumentChunk.is_active.is_(True)).scalar() or 0
    )
    structured_count = (
        db.query(func.count(DocumentChunk.id))
        .filter(
            DocumentChunk.is_active.is_(True),
            DocumentChunk.content_type == "structured_fact",
        )
        .scalar()
        or 0
    )
    report_count = db.query(func.count(Report.id)).scalar() or 0
    indexed_docs = (
        db.query(func.count(Document.id)).filter(Document.embedding_completed.is_(True)).scalar() or 0
    )

    llm = probe_local_llm()
    provider = settings.assistant_llm_provider
    local_ok = bool(llm.get("available") or llm.get("reachable")) if isinstance(llm, dict) else False
    local_wanted = provider in {"local_qwen", "ollama", "qwen"}

    ai_message = None
    if local_wanted and not local_ok:
        ai_message = (
            "Local AI unavailable. Start Ollama and load the configured model "
            f"({settings.local_llm_model}) to enable AI Assistant features."
        )

    return {
        "application": {
            "name": settings.app_name,
            "version": "0.7.0",
            "environment": settings.app_env,
            "demo_mode": settings.demo_mode,
            "status": "operational",
        },
        "ai_assistant": {
            "provider": provider,
            "model": settings.local_llm_model if local_wanted else settings.llm_model,
            "local_enabled": settings.local_llm_enabled,
            "local_base_url": settings.local_llm_base_url if settings.local_llm_enabled else None,
            "api_key_configured": bool(settings.llm_api_key),
            "connection_health": (
                "ok"
                if (local_ok or (not local_wanted and (bool(settings.llm_api_key) or provider == "mock")))
                else "unavailable"
            ),
            "local_probe": llm,
            "message": ai_message,
            "read_only": True,
        },
        "document_processing": {
            "ocr_engine": "Tesseract",
            "ocr_language": settings.ocr_language,
            "supported_types": ["pdf", "excel", "image"],
            "documents": doc_count,
            "indexed_documents": indexed_docs,
            "extracted_facts": fact_count,
            "read_only": True,
        },
        "system": {
            "database": "sqlite" if settings.use_sqlite else "postgresql",
            "database_status": "ok",
            "vector_index": {
                "active_chunks": chunk_count,
                "structured_facts": structured_count,
                "embedding_provider": settings.embedding_provider,
                "status": "ok" if chunk_count >= 0 else "unknown",
                "technology": "SQLite JSON embeddings (local) / pgvector-ready",
            },
            "storage": {
                "path": str(docs_root),
                "status": "ok" if storage_ok else "missing",
            },
            "reports": report_count,
            "read_only": True,
        },
        "security": {
            "auth_mode": "jwt" if settings.auth_required else "jwt_optional_demo",
            "auth_required": settings.auth_required,
            "current_user": user.username,
            "role": user.role,
            "permissions": sorted(ROLE_PERMISSIONS.get(user.role, set())),
            "read_only": True,
            "note": "Passwords are bcrypt-hashed. Secrets are never returned by this API.",
        },
        "technical_details": {
            "llm_extraction_provider": settings.llm_provider,
            "chunk_size": settings.chunk_size,
            "search_top_k": settings.search_top_k,
            "min_similarity_threshold": settings.min_similarity_threshold,
            "index_verified_facts": settings.index_verified_facts,
        },
    }


@router.get("/audit-logs")
def list_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("audit.read")),
) -> dict[str, Any]:
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    rows = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    items = [
        {
            "id": r.id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "actor": r.actor,
            "details": r.details,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"total": len(items), "items": items}
