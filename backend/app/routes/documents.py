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
from app.models import Document, DocumentChunk, DocumentStatus, ExtractedFact, ExtractionJob, GeologicalFact
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
    GeologicalFactOut,
    GeologicalFactReviewAction,
    GeologicalFactsResponse,
    GeologicalPipelineOut,
    IndexResultOut,
    ProcessingStatusOut,
    ValidationConflictOut,
)
from app.geology.review import GeologicalReviewError, review_geological_fact
from app.geology.service import run_geological_pipeline
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


def _geo_fact_out(row: GeologicalFact) -> GeologicalFactOut:
    return GeologicalFactOut(
        id=row.id,
        domain=getattr(row, "domain", None) or "geological",
        metric_kind=getattr(row, "metric_kind", None),
        borehole_id=row.borehole_id,
        seam_name=row.seam_name,
        seam_status=getattr(row, "seam_status", None),
        depth=row.depth,
        depth_unit=row.depth_unit,
        depth_normalized_m=row.depth_normalized_m,
        thickness=row.thickness,
        thickness_unit=row.thickness_unit,
        thickness_normalized_m=row.thickness_normalized_m,
        thickness_min=getattr(row, "thickness_min", None),
        thickness_max=getattr(row, "thickness_max", None),
        thickness_min_normalized_m=getattr(row, "thickness_min_normalized_m", None),
        thickness_max_normalized_m=getattr(row, "thickness_max_normalized_m", None),
        depth_min=getattr(row, "depth_min", None),
        depth_max=getattr(row, "depth_max", None),
        depth_min_normalized_m=getattr(row, "depth_min_normalized_m", None),
        depth_max_normalized_m=getattr(row, "depth_max_normalized_m", None),
        original_value=getattr(row, "original_value", None),
        original_unit=getattr(row, "original_unit", None),
        value_qualifier=getattr(row, "value_qualifier", None),
        lithology=row.lithology,
        geological_formation=row.geological_formation,
        geological_structure=row.geological_structure,
        coal_quality_parameter=row.coal_quality_parameter,
        coal_quality_value=row.coal_quality_value,
        coal_quality_unit=row.coal_quality_unit,
        source_document_id=row.document_id,
        source_page=row.source_page,
        source_location=row.source_location,
        evidence_text=row.evidence_text,
        extraction_confidence=row.extraction_confidence or 0.0,
        status=row.status,
        original_extracted_value=getattr(row, "original_extracted_value", None),
        corrected_value=getattr(row, "corrected_value", None),
        corrected_unit=getattr(row, "corrected_unit", None),
        corrected_by=getattr(row, "corrected_by", None),
        corrected_at=getattr(row, "corrected_at", None),
        correction_reason=getattr(row, "correction_reason", None),
        fact_version=getattr(row, "fact_version", None) or 1,
        warnings=row.warnings,
        table_context=row.table_context,
        created_at=row.created_at,
    )


def _build_detail(db: Session, doc: Document) -> DocumentDetailOut:
    pages = [DocumentPageOut.model_validate(p) for p in sorted(doc.pages, key=lambda x: x.page_number)]
    facts = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.document_id == doc.id)
        .order_by(ExtractedFact.page_number, ExtractedFact.field_name)
        .all()
    )
    geo_facts = (
        db.query(GeologicalFact)
        .filter(GeologicalFact.document_id == doc.id)
        .order_by(GeologicalFact.source_page, GeologicalFact.created_at)
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
        geological_facts=[_geo_fact_out(g) for g in geo_facts],
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


@router.get("/{document_id}/geological-facts", response_model=GeologicalFactsResponse)
def list_geological_facts(
    document_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("documents.read")),
) -> GeologicalFactsResponse:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    rows = (
        db.query(GeologicalFact)
        .filter(GeologicalFact.document_id == document_id)
        .order_by(GeologicalFact.source_page, GeologicalFact.created_at)
        .all()
    )
    return GeologicalFactsResponse(total=len(rows), items=[_geo_fact_out(r) for r in rows])


@router.post(
    "/{document_id}/geological-facts/{fact_id}/review",
    response_model=GeologicalFactOut,
)
def review_document_geological_fact(
    document_id: str,
    fact_id: str,
    body: GeologicalFactReviewAction,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("review.act")),
) -> GeologicalFactOut:
    """Human review for a geological fact — never silently promotes review_required."""
    row = (
        db.query(GeologicalFact)
        .filter(GeologicalFact.id == fact_id, GeologicalFact.document_id == document_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Geological fact not found")
    try:
        updated = review_geological_fact(
            db,
            fact_id,
            action=body.action,
            corrected_value=body.corrected_value,
            corrected_unit=body.corrected_unit,
            reviewer=body.reviewer or user.username,
            reason=body.reason,
        )
        db.commit()
        db.refresh(updated)
    except GeologicalReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _geo_fact_out(updated)


@router.post("/{document_id}/geological-pipeline", response_model=GeologicalPipelineOut)
def run_document_geological_pipeline(
    document_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("documents.read")),
) -> GeologicalPipelineOut:
    """Re-run G1 classification + geological extraction on existing page text."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.pages:
        raise HTTPException(status_code=400, detail="Document has no extracted pages. Process the document first.")
    result = run_geological_pipeline(db, doc)
    return GeologicalPipelineOut(**result)


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
    else:
        # Soft version link: same original filename → treat as new version of latest copy
        # (prevents duplicate uploads from appearing as unrelated documents in retrieval)
        from app.assistant.document_resolver import filename_key

        key = filename_key(original_name)
        if key:
            siblings = [
                d
                for d in db.query(Document).all()
                if filename_key(d.original_filename or d.filename) == key
            ]
            if siblings:
                siblings.sort(
                    key=lambda d: (
                        d.version or 1,
                        d.created_at.timestamp() if d.created_at else 0,
                    ),
                    reverse=True,
                )
                latest = siblings[0]
                root = latest
                while root.parent_document_id:
                    nxt = db.query(Document).filter(Document.id == root.parent_document_id).first()
                    if not nxt:
                        break
                    root = nxt
                max_ver = max((d.version or 1) for d in siblings)
                version = max_ver + 1
                parent_id = root.id
                replaces_id = latest.id

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
