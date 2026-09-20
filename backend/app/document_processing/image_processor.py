"""Image document OCR."""

from __future__ import annotations

from pathlib import Path

from app.document_processing.ocr_processor import ocr_image_path
from app.document_processing.types import ExtractedPage, ProcessingResult
from app.models import SourceType


def process_image(path: Path) -> ProcessingResult:
    text = ocr_image_path(str(path))
    page = ExtractedPage(
        page_number=1,
        text=text,
        source_type=SourceType.IMAGE.value,
        source_location="image:1",
    )
    return ProcessingResult(
        pages=[page],
        is_scanned=True,
        ocr_used=True,
        file_type="image",
        page_count=1,
        meta={"mode": "image_ocr"},
        stage="completed",
    )
