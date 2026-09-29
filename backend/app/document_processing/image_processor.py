"""Image document OCR via configurable OCR strategy (Paddle → Tesseract fallback)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.document_processing.ocr.strategy import ocr_pil_image_detailed
from app.document_processing.types import ExtractedPage, ProcessingResult
from app.models import SourceType


def process_image(path: Path) -> ProcessingResult:
    image = Image.open(path)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    result = ocr_pil_image_detailed(image, page_number=1)
    meta = {
        "mode": "image_ocr",
        "ocr_engine": result.engine,
        "ocr_mean_confidence": result.mean_confidence,
        "ocr_word_count": result.word_count,
    }
    if result.boxes:
        meta["ocr_boxes"] = result.boxes[:200]
    page = ExtractedPage(
        page_number=1,
        text=result.text,
        source_type=SourceType.IMAGE.value,
        source_location="image:1",
        content_meta=meta,
    )
    return ProcessingResult(
        pages=[page],
        is_scanned=True,
        ocr_used=True,
        file_type="image",
        page_count=1,
        meta={"mode": "image_ocr", "ocr_engine": result.engine},
        stage="completed",
    )
