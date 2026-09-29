"""Document ingestion & preprocessing (Phase 2)."""

from app.document_processing.service import get_processing_status, process_document, process_file

__all__ = ["process_document", "process_file", "get_processing_status"]
