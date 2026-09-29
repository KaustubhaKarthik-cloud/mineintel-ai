"""Document processing orchestrator (Phase 2).

UPLOAD → validate → detect type → extract / OCR → store page-level text.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.document_processing.excel_processor import process_excel
from app.document_processing.image_processor import process_image
from app.document_processing.ocr_processor import OCRUnavailableError
from app.document_processing.pdf_processor import process_pdf
from app.document_processing.types import ProcessingResult
from app.models import Document, DocumentPage, DocumentStatus
from app.utils.files import classify_file_kind, detect_extension


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def process_file(path: Path) -> ProcessingResult:
    """Route a file on disk to the correct processor."""
    ext = detect_extension(path.name)
    kind = classify_file_kind(ext)

    if kind == "pdf":
        return process_pdf(path)
    if kind == "excel":
        return process_excel(path)
    if kind == "image":
        return process_image(path)
    raise RuntimeError(f"No processor for file type '{ext}'.")


def persist_pages(db: Session, document: Document, result: ProcessingResult) -> None:
    # Replace any previous pages (reprocess-safe)
    document.pages.clear()
    db.flush()
    for page in result.pages:
        db.add(
            DocumentPage(
                document_id=document.id,
                page_number=page.page_number,
                text=page.text or "",
                source_type=page.source_type,
                sheet_name=page.sheet_name,
                source_location=page.source_location,
                char_count=len(page.text or ""),
                content_meta=page.content_meta,
            )
        )


def process_document(db: Session, document: Document) -> Document:
    """Run the full Phase 2 pipeline for a document row and persist results."""
    document.status = DocumentStatus.PROCESSING.value
    document.processing_stage = "extracting_text"
    document.processing_started_at = _utcnow()
    document.error_message = None
    db.commit()
    db.refresh(document)

    path = Path(document.file_path)
    if not path.is_file():
        document.status = DocumentStatus.FAILED.value
        document.processing_stage = "failed"
        document.error_message = "Stored file is missing on disk."
        document.processing_completed_at = _utcnow()
        db.commit()
        return document

    try:
        kind = classify_file_kind(detect_extension(document.original_filename))
        if kind == "pdf":
            document.processing_stage = "detecting_pdf_type"
            db.commit()

        result = process_file(path)

        if result.ocr_used:
            document.processing_stage = "ocr"
            db.commit()

        persist_pages(db, document, result)

        document.file_type = result.file_type or document.file_type
        document.page_count = result.page_count
        document.is_scanned = result.is_scanned
        document.ocr_completed = result.ocr_used
        document.extraction_completed = False  # Phase 3 AI extraction
        document.meta = {**(document.meta or {}), **result.meta}
        document.status = DocumentStatus.COMPLETED.value
        document.processing_stage = "classifying"
        document.processing_completed_at = _utcnow()
        document.error_message = None
        db.commit()
        db.refresh(document)

        # G1 — domain classification + optional geological fact extraction (rule-based).
        # Failures here must not fail Phase 2 text extraction.
        try:
            from app.geology.service import run_geological_pipeline

            run_geological_pipeline(db, document)
            db.refresh(document)
        except Exception as exc:  # noqa: BLE001
            document.meta = {
                **(document.meta or {}),
                "g1_error": str(exc)[:400],
            }
            db.commit()
            db.refresh(document)

        document.processing_stage = "completed"
        db.commit()

        # Auto-index so assistant/RAG can retrieve freshly extracted text.
        # Failures are recorded on the document but do not fail Phase 2 extraction.
        try:
            document.processing_stage = "indexing"
            db.commit()
            from app.retrieval.service import index_document

            document = index_document(db, document.id)
            db.refresh(document)
            if document.index_status == "indexed":
                document.processing_stage = "completed"
                db.commit()
        except Exception as exc:  # noqa: BLE001
            document.processing_stage = "completed"
            document.index_error = (document.index_error or str(exc))[:500]
            db.commit()
            db.refresh(document)
        return document

    except OCRUnavailableError as exc:
        document.status = DocumentStatus.FAILED.value
        document.processing_stage = "failed"
        document.error_message = str(exc)
        document.processing_completed_at = _utcnow()
        db.commit()
        db.refresh(document)
        return document
    except Exception as exc:  # noqa: BLE001
        document.status = DocumentStatus.FAILED.value
        document.processing_stage = "failed"
        # User-safe message — no stack traces
        document.error_message = f"Processing failed: {exc.__class__.__name__}. Check the file and try again."
        document.processing_completed_at = _utcnow()
        document.meta = {**(document.meta or {}), "internal_error": str(exc)[:500]}
        db.commit()
        db.refresh(document)
        return document


def get_processing_status(document: Document) -> dict:
    return {
        "id": document.id,
        "status": document.status,
        "processing_stage": document.processing_stage,
        "error_message": document.error_message,
        "page_count": document.page_count,
        "is_scanned": document.is_scanned,
        "ocr_completed": document.ocr_completed,
        "processing_started_at": document.processing_started_at,
        "processing_completed_at": document.processing_completed_at,
    }
