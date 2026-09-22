"""Configurable OCR strategy: PaddleOCR primary, Tesseract fallback.

Environment / settings:
  OCR_ENGINE=paddle|tesseract|auto   (default: paddle)
  OCR_FALLBACK=tesseract|none        (default: tesseract)

Does not remove Tesseract. Digital PDF text extraction stays in pdf_processor
and never routes through this module.
"""

from __future__ import annotations

import logging
from typing import Optional

from PIL import Image

from app.config import get_settings
from app.document_processing.ocr_processor import (
    OCRResult,
    OCRUnavailableError,
    ocr_available as tesseract_available,
    ocr_pil_image_detailed as tesseract_ocr_detailed,
)

logger = logging.getLogger(__name__)


def _usable(result: OCRResult, *, min_chars: int = 8) -> bool:
    return bool(result and (result.text or "").strip() and len(result.text.strip()) >= min_chars)


def resolved_engine() -> str:
    """Effective primary engine name after availability checks."""
    settings = get_settings()
    preferred = (settings.ocr_engine or "paddle").strip().lower()
    if preferred in {"tesseract", "tess"}:
        return "tesseract"
    if preferred in {"paddle", "paddleocr", "auto"}:
        from app.document_processing.ocr.paddle_ocr import paddle_available

        if paddle_available():
            return "paddle"
        if preferred == "paddle":
            # Requested paddle but missing — still allow fallback path
            return "paddle"
        return "tesseract"
    return preferred


def ocr_pil_image_detailed(
    image: Image.Image,
    lang: Optional[str] = None,
    *,
    page_number: int = 1,
) -> OCRResult:
    """OCR a PIL image using configured primary engine with optional fallback."""
    settings = get_settings()
    primary = (settings.ocr_engine or "paddle").strip().lower()
    fallback = (settings.ocr_fallback or "tesseract").strip().lower()
    min_chars = int(getattr(settings, "ocr_min_usable_chars", 8) or 8)

    engines: list[str] = []
    if primary in {"paddle", "paddleocr", "auto"}:
        engines.append("paddle")
    elif primary in {"tesseract", "tess"}:
        engines.append("tesseract")
    else:
        engines.append(primary)

    if fallback in {"tesseract", "tess"} and "tesseract" not in engines:
        engines.append("tesseract")
    if fallback in {"paddle", "paddleocr"} and "paddle" not in engines:
        engines.append("paddle")

    last_error: Exception | None = None
    for engine in engines:
        try:
            if engine == "paddle":
                from app.document_processing.ocr.paddle_ocr import (
                    PaddleOCRUnavailableError,
                    ocr_pil_image_detailed_paddle,
                    paddle_available,
                )

                if not paddle_available():
                    raise PaddleOCRUnavailableError("PaddleOCR not installed")
                result = ocr_pil_image_detailed_paddle(image, page_number=page_number)
                if _usable(result, min_chars=min_chars):
                    return result
                logger.warning(
                    "PaddleOCR returned insufficient text (page=%s, chars=%s); trying fallback",
                    page_number,
                    len((result.text or "").strip()),
                )
                last_error = PaddleOCRUnavailableError("PaddleOCR returned no usable text")
                continue

            if engine == "tesseract":
                if not tesseract_available():
                    raise OCRUnavailableError("Tesseract not available")
                result = tesseract_ocr_detailed(image, lang=lang)
                # annotate engine (dataclass may already default)
                result.engine = "tesseract"
                result.page = page_number
                if _usable(result, min_chars=min_chars):
                    return result
                last_error = OCRUnavailableError("Tesseract returned no usable text")
                continue

            raise OCRUnavailableError(f"Unknown OCR engine: {engine}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("OCR engine %s failed (page=%s): %s", engine, page_number, exc)
            continue

    if last_error:
        raise OCRUnavailableError(str(last_error)) from last_error
    raise OCRUnavailableError("No OCR engine produced usable text.")
