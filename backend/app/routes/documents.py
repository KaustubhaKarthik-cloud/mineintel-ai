"""Document upload, listing, detail, and Phase 3 extraction APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.ai_extraction.service import ExtractionServiceError, run_batch_extraction, run_extraction
from app.auth.deps import AuthUser, get_current_user, require_permission
from app.database import get_db
from app.document_processing.service import get_processing_status, process_document
from app.models import Document, DocumentChunk, DocumentStatus, ExtractedFact, ExtractionJob
from app.retrieval.service import IndexingError, index_document
from app.schemas import (
    BatchExtractRequest,
    BatchExtractResponse,
    ConflictEvidenceOut,
    DocumentDetailOut,
    DocumentListResponse,
    DocumentOut,
    DocumentPageOut,
    ExtractedFactOut,
    ExtractionJobOut,
    ExtractionSummaryOut,
    IndexResultOut,
    ProcessingStatusOut,
    ValidationConflictOut,
)
from app.services.audit import write_audit
from app.utils.files import (
    FileValidationError,
    build_storage_name,
    classify_file_kind,
    documents_root,
    new_document_id,
    sanitize_filename,
    validate_extension,
    validate_file_size,
    validate_magic_bytes,
    validate_mime,
)
from app.validation.service import conflicts_for_fact_ids, list_conflicts

router = APIRouter()


def _conflict_out(row) -> ValidationConflictOut:
    evidence = [
        ConflictEvidenceOut(
            id=e.id,
            document_id=e.document_id,
            document_page_id=e.document_page_id,
            extracted_fact_id=e.extracted_fact_id,
            document_name=e.document_name,
            document_version=e.document_version or 1,
            page_number=e.page_number,
            sheet_name=e.sheet_name,
            source_location=e.source_location,
            value=e.value,
            unit=e.unit,
            numeric_value=e.numeric_value,
            normalized_value=e.normalized_value,
            evidence_text=e.evidence_text,
            is_calculated=bool(e.is_calculated),
            label=e.label,
        )
        for e in (row.evidence_items or [])
    ]
    return ValidationConflictOut(
        id=row.id,
        fingerprint=row.fingerprint,
        conflict_type=row.conflict_type,
        entity_name=row.entity_name,
        field_name=row.field_name,
        period=row.period,
        status=row.status,
        severity=row.severity,
        description=row.description,
        selected_value=row.selected_value,
        selected_unit=row.selected_unit,
        resolution_reason=row.resolution_reason,
        reviewer=row.reviewer,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        evidence=evidence,
    )


def _to_document_out(doc: Document) -> DocumentOut:
    data = DocumentOut.model_validate(doc)
    return data.model_copy(update={"upload_date": doc.created_at})


def _build_detail(db: Session, doc: Document) -> DocumentDetailOut:
    pages = [DocumentPageOut.model_validate(p) for p in sorted(doc.pages, key=lambda x: x.page_number)]
    facts = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.document_id == doc.id)
        .order_by(ExtractedFact.page_number, ExtractedFact.field_name)
        .all()
    )
    job = (
        db.query(ExtractionJob)
        .filter(ExtractionJob.document_id == doc.id)
        .order_by(desc(ExtractionJob.created_at))
        .first()
    )
    fact_conflicts = conflicts_for_fact_ids(db, [f.id for f in facts])
    fact_outs = []
    for f in facts:
        confs = fact_conflicts.get(f.id, [])
        out = ExtractedFactOut.model_validate(f)
        fact_outs.append(
            out.model_copy(
                update={
                    "has_conflict": bool(confs),
                    "conflict_ids": [c.id for c in confs],
                }
            )
        )
    doc_conflicts = list_conflicts(db, document_id=doc.id)
    base = _to_document_out(doc)
    return DocumentDetailOut(
        **base.model_dump(),
        pages=pages,
        meta=doc.meta,
        facts=fact_outs,
        latest_extraction_job=ExtractionJobOut.model_validate(job) if job else None,
        conflicts=[_conflict_out(c) for c in doc_conflicts],
    )


@router.get("", response_model=DocumentListResponse)
def list_documents(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("documents.read")),
) -> DocumentListResponse:
    docs = db.query(Document).order_by(desc(Document.created_at)).all()
    items = [_to_document_out(d) for d in docs]
    return DocumentListResponse(total=len(items), items=items)


@router.post("/extract", response_model=BatchExtractResponse)
def extract_batch(body: BatchExtractRequest, db: Session = Depends(get_db)) -> BatchExtractResponse:
    if not body.document_ids:
        raise HTTPException(status_code=400, detail="document_ids is required")
    return BatchExtractResponse(results=run_batch_extraction(db, body.document_ids))


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentDetailOut:
    doc = (
        db.query(Document)
        .options(joinedload(Document.pages))
        .filter(Document.id == document_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _build_detail(db, doc)


@router.get("/{document_id}/file")
def download_document_file(document_id: str, db: Session = Depends(get_db)):
    """Serve the original stored document for viewing / download."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = Path(doc.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Original file missing on disk")
    media = doc.mime_type or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=doc.original_filename or doc.filename,
        content_disposition_type="inline",
    )


@router.get("/{document_id}/status", response_model=ProcessingStatusOut)
def document_status(document_id: str, db: Session = Depends(get_db)) -> ProcessingStatusOut:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return ProcessingStatusOut(**get_processing_status(doc))


@router.get("/{document_id}/facts", response_model=list[ExtractedFactOut])
def list_facts(document_id: str, db: Session = Depends(get_db)) -> list[ExtractedFactOut]:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    facts = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.document_id == document_id)
        .order_by(ExtractedFact.page_number, ExtractedFact.field_name)
        .all()
    )
    return [ExtractedFactOut.model_validate(f) for f in facts]


@router.post("/{document_id}/extract", response_model=ExtractionSummaryOut)
def extract_document(
    document_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("documents.read")),
) -> ExtractionSummaryOut:
    try:
        job = run_extraction(db, document_id)
    except ExtractionServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_audit(
        db,
        action="EXTRACTION_COMPLETED",
        actor=user.username,
        entity_type="document",
        entity_id=document_id,
        details={"job_id": job.id, "facts_count": job.facts_count, "status": job.status},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    facts = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.job_id == job.id)
        .order_by(ExtractedFact.page_number, ExtractedFact.field_name)
        .all()
    )
    return ExtractionSummaryOut(
        job=ExtractionJobOut.model_validate(job),
        facts=[ExtractedFactOut.model_validate(f) for f in facts],
    )


@router.post("/{document_id}/index", response_model=IndexResultOut)
def index_document_endpoint(
    document_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("documents.read")),
) -> IndexResultOut:
    try:
        doc = index_document(db, document_id)
    except IndexingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    chunk_count = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id, DocumentChunk.is_active.is_(True))
        .count()
    )
    write_audit(
        db,
        action="DOCUMENT_INDEXED",
        actor=user.username,
        entity_type="document",
        entity_id=document_id,
        details={"chunk_count": chunk_count, "index_status": doc.index_status},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    return IndexResultOut(
        document_id=doc.id,
        index_status=doc.index_status,
        embedding_completed=doc.embedding_completed,
        indexed_at=doc.indexed_at,
        chunk_count=chunk_count,
        index_error=doc.index_error,
    )


@router.post("/upload", response_model=DocumentDetailOut)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    mine_name: str = Form(default=""),
    document_category: str = Form(default="General"),
    uploaded_by: str = Form(default=""),
    parent_document_id: str = Form(default=""),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("documents.upload")),
) -> DocumentDetailOut:
    """Validate, store original, run Phase 2 text extraction / OCR, return detail.

    If parent_document_id is provided, creates a new version without overwriting the original.
    """
    original_name = sanitize_filename(file.filename or "upload.bin")

    try:
        ext = validate_extension(original_name)
    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw = await file.read()
    try:
        validate_file_size(len(raw))
        validate_magic_bytes(raw, ext)
    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mime = validate_mime(ext, file.content_type)
    doc_id = new_document_id()
    storage_name = build_storage_name(original_name, doc_id)
    dest = documents_root() / "original" / storage_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)

    kind = classify_file_kind(ext)
    display_type = kind if kind != "unknown" else ext.lstrip(".")

    version = 1
    parent_id: Optional[str] = None
    replaces_id: Optional[str] = None
    parent_ref = (parent_document_id or "").strip()
    if parent_ref:
        parent = db.query(Document).filter(Document.id == parent_ref).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent document not found for versioning")
        # Walk to root of version chain
        root = parent
        while root.parent_document_id:
            next_parent = db.query(Document).filter(Document.id == root.parent_document_id).first()
            if not next_parent:
                break
            root = next_parent
        all_versions = db.query(Document).filter(
            (Document.id == root.id)
            | (Document.parent_document_id == root.id)
            | (Document.replaces_document_id == root.id)
        ).all()
        max_ver = max((d.version or 1) for d in all_versions) if all_versions else (parent.version or 1)
        version = max_ver + 1
        parent_id = root.id
        replaces_id = parent.id

    actor = (uploaded_by or "").strip() or user.username
    document = Document(
        id=doc_id,
        filename=storage_name,
        original_filename=original_name,
        file_path=str(dest.resolve()),
        file_type=display_type,
        file_size=len(raw),
        mime_type=mime,
        status=DocumentStatus.UPLOADED.value,
        processing_stage="uploaded",
        version=version,
        mine_name=mine_name or None,
        document_category=document_category or "General",
        uploaded_by=actor,
        parent_document_id=parent_id,
        replaces_document_id=replaces_id,
        meta={"extension": ext, "version_of": parent_id},
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    write_audit(
        db,
        action="DOCUMENT_UPLOADED",
        actor=actor,
        entity_type="document",
        entity_id=document.id,
        details={
            "filename": original_name,
            "version": version,
            "parent_document_id": parent_id,
            "file_size": len(raw),
        },
        ip_address=request.client.host if request.client else None,
        commit=True,
    )

    document = process_document(db, document)

    write_audit(
        db,
        action="DOCUMENT_PROCESSED",
        actor=actor,
        entity_type="document",
        entity_id=document.id,
        details={
            "status": document.status,
            "page_count": document.page_count,
            "is_scanned": document.is_scanned,
            "ocr_completed": document.ocr_completed,
        },
        commit=True,
    )

    full = (
        db.query(Document)
        .options(joinedload(Document.pages))
        .filter(Document.id == document.id)
        .first()
    )
    assert full is not None
    return _build_detail(db, full)


@router.get("/{document_id}/versions")
def list_document_versions(
    document_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("documents.read")),
) -> dict[str, Any]:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    root_id = doc.parent_document_id or doc.id
    # Collect chain: root + any with parent=root or replaces pointing into family
    family = (
        db.query(Document)
        .filter(
            (Document.id == root_id)
            | (Document.parent_document_id == root_id)
            | (Document.replaces_document_id == document_id)
            | (Document.id == document_id)
        )
        .order_by(Document.version.asc(), Document.created_at.asc())
        .all()
    )
    # Deduplicate by id
    seen: set[str] = set()
    items = []
    for d in family:
        if d.id in seen:
            continue
        seen.add(d.id)
        items.append(
            {
                "id": d.id,
                "version": d.version or 1,
                "original_filename": d.original_filename,
                "status": d.status,
                "uploaded_by": d.uploaded_by,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "index_status": d.index_status,
                "parent_document_id": d.parent_document_id,
                "replaces_document_id": d.replaces_document_id,
            }
        )
    items.sort(key=lambda x: (x["version"], x["created_at"] or ""))
    return {"root_document_id": root_id, "total": len(items), "items": items}


@router.post("/{document_id}/reprocess", response_model=DocumentDetailOut)
def reprocess_document(document_id: str, db: Session = Depends(get_db)) -> DocumentDetailOut:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not Path(doc.file_path).is_file():
        raise HTTPException(status_code=400, detail="Original file missing on disk")

    doc.version = (doc.version or 1) + 1
    if doc.index_status == "indexed" or doc.embedding_completed:
        from app.models import IndexStatus

        doc.index_status = IndexStatus.STALE.value
    db.commit()
    process_document(db, doc)

    full = (
        db.query(Document)
        .options(joinedload(Document.pages))
        .filter(Document.id == document_id)
        .first()
    )
    assert full is not None
    return _build_detail(db, full)
