"""Digital PDF text extraction and scanned-PDF OCR via PyMuPDF.

Native/text PDFs use embedded text only (no OCR).
Scanned/image PDFs use the configurable OCR strategy (Paddle primary, Tesseract fallback).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from app.config import get_settings
from app.document_processing.ocr.strategy import ocr_pil_image_detailed, resolved_engine
from app.document_processing.ocr_processor import OCRUnavailableError
from app.document_processing.ocr_refine import looks_like_numeric_table, merge_ocr_decimals
from app.document_processing.types import ExtractedPage, ProcessingResult
from app.models import SourceType


def _page_text_density(pages_text: list[str]) -> float:
    if not pages_text:
        return 0.0
    return sum(len(t.strip()) for t in pages_text) / len(pages_text)


def extract_digital_pdf(path: Path) -> list[ExtractedPage]:
    doc = fitz.open(path)
    pages: list[ExtractedPage] = []
    try:
        for i, page in enumerate(doc):
            text = (page.get_text("text") or "").strip()
            pages.append(
                ExtractedPage(
                    page_number=i + 1,
                    text=text,
                    source_type=SourceType.PDF_PAGE.value,
                    source_location=f"page:{i + 1}",
                )
            )
    finally:
        doc.close()
    return pages


def _render_page_image(page: fitz.Page, dpi: int):
    from PIL import Image

    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _content_meta_from_ocr(base, *, base_dpi: int, refined: bool, hi_dpi: int, detail_mean) -> dict:
    meta = {
        "ocr_dpi": base_dpi,
        "ocr_engine": getattr(base, "engine", None) or resolved_engine(),
        "ocr_refined": refined,
        "ocr_detail_dpi": hi_dpi if refined else None,
        "ocr_mean_confidence": base.mean_confidence,
        "ocr_detail_mean_confidence": detail_mean,
        "ocr_word_count": base.word_count,
        "ocr_low_confidence_decimals": base.low_confidence_decimals,
        "ocr_low_confidence_words": base.low_confidence_words[:20],
    }
    boxes = getattr(base, "boxes", None) or []
    if boxes:
        # Cap stored boxes for DB size while keeping page-level evidence
        meta["ocr_boxes"] = boxes[:200]
    return meta


def ocr_pdf_pages(
    path: Path,
    dpi: Optional[int] = None,
    *,
    detail_dpi: Optional[int] = None,
    refine: Optional[bool] = None,
) -> list[ExtractedPage]:
    """Render each PDF page to an image and OCR it.

    When a page looks like a numeric production table, a higher-DPI detail pass
    corrects digit-confusion misreads using neighbor consensus — without
    hard-coding document names or expected values.
    """
    settings = get_settings()
    base_dpi = dpi if dpi is not None else settings.ocr_dpi
    hi_dpi = detail_dpi if detail_dpi is not None else settings.ocr_detail_dpi
    do_refine = settings.ocr_detail_refine if refine is None else refine

    doc = fitz.open(path)
    pages: list[ExtractedPage] = []
    try:
        for i, page in enumerate(doc):
            page_number = i + 1
            image = _render_page_image(page, base_dpi)
            base = ocr_pil_image_detailed(image, page_number=page_number)
            text = base.text
            refined = False
            detail_mean = None
            if do_refine and hi_dpi > base_dpi and looks_like_numeric_table(text):
                detail = ocr_pil_image_detailed(
                    _render_page_image(page, hi_dpi), page_number=page_number
                )
                detail_mean = detail.mean_confidence
                merged = merge_ocr_decimals(text, detail.text)
                if merged != text:
                    text = merged
                    refined = True

            content_meta = _content_meta_from_ocr(
                base,
                base_dpi=base_dpi,
                refined=refined,
                hi_dpi=hi_dpi,
                detail_mean=detail_mean,
            )
            # Optional assistive table hints (never replaces structured_table)
            try:
                from app.document_processing.ocr.table_assist import extract_table_hints_from_image

                hints = extract_table_hints_from_image(
                    image,
                    page_number=page_number,
                    source_document=path.name,
                )
                if hints:
                    content_meta["ocr_table_assist"] = hints
            except Exception:  # noqa: BLE001
                pass

            pages.append(
                ExtractedPage(
                    page_number=page_number,
                    text=text,
                    source_type=SourceType.OCR_PAGE.value,
                    source_location=f"page:{page_number}:ocr",
                    content_meta=content_meta,
                )
            )
    finally:
        doc.close()
    return pages


def process_pdf(path: Path) -> ProcessingResult:
    settings = get_settings()
    digital_pages = extract_digital_pdf(path)
    density = _page_text_density([p.text for p in digital_pages])
    is_scanned = density < settings.pdf_digital_text_threshold

    if not is_scanned:
        return ProcessingResult(
            pages=digital_pages,
            is_scanned=False,
            ocr_used=False,
            file_type="pdf",
            page_count=len(digital_pages),
            meta={"text_density": density, "mode": "digital"},
            stage="completed",
        )

    try:
        ocr_pages = ocr_pdf_pages(path)
    except OCRUnavailableError:
        raise

    engines_used = sorted(
        {
            (p.content_meta or {}).get("ocr_engine")
            for p in ocr_pages
            if (p.content_meta or {}).get("ocr_engine")
        }
    )
    return ProcessingResult(
        pages=ocr_pages,
        is_scanned=True,
        ocr_used=True,
        file_type="pdf",
        page_count=len(ocr_pages),
        meta={
            "text_density": density,
            "mode": "scanned_ocr",
            "ocr_dpi": settings.ocr_dpi,
            "ocr_engine_primary": settings.ocr_engine,
            "ocr_fallback": settings.ocr_fallback,
            "ocr_engines_used": engines_used,
        },
        stage="completed",
    )
