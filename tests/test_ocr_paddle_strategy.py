"""OCR strategy + PaddleOCR integration tests (Tesseract remains fallback)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from app.document_processing.ocr_processor import OCRResult
from app.models import FactStatus, ReviewStatus


def _make_text_image(tmp_path: Path, text: str = "Mine B produced 3.9 MT") -> Path:
    img = Image.new("RGB", (640, 200), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 80), text, fill=(0, 0, 0))
    path = tmp_path / "ocr_sample.png"
    img.save(path)
    return path


def test_ocr_strategy_falls_back_to_tesseract_when_paddle_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_ENGINE", "paddle")
    monkeypatch.setenv("OCR_FALLBACK", "tesseract")
    from app import config as config_mod

    config_mod.get_settings.cache_clear()

    paddle_empty = OCRResult(text="", mean_confidence=None, word_count=0, engine="paddle", page=1)
    tess = OCRResult(
        text="fallback text from tesseract",
        mean_confidence=88.0,
        word_count=4,
        engine="tesseract",
        page=1,
    )

    with patch(
        "app.document_processing.ocr.paddle_ocr.paddle_available", return_value=True
    ), patch(
        "app.document_processing.ocr.paddle_ocr.ocr_pil_image_detailed_paddle",
        return_value=paddle_empty,
    ), patch(
        "app.document_processing.ocr.strategy.tesseract_available", return_value=True
    ), patch(
        "app.document_processing.ocr.strategy.tesseract_ocr_detailed", return_value=tess
    ):
        from app.document_processing.ocr.strategy import ocr_pil_image_detailed

        img = Image.open(_make_text_image(tmp_path))
        out = ocr_pil_image_detailed(img, page_number=1)
        assert out.engine == "tesseract"
        assert "tesseract" in out.text

    config_mod.get_settings.cache_clear()


def test_ocr_strategy_uses_paddle_when_usable(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_ENGINE", "paddle")
    monkeypatch.setenv("OCR_FALLBACK", "tesseract")
    from app import config as config_mod

    config_mod.get_settings.cache_clear()

    paddle_ok = OCRResult(
        text="CIL coal production 85.81 MT",
        mean_confidence=92.0,
        word_count=5,
        boxes=[{"text": "CIL", "confidence": 95.0, "bbox": [[1, 1], [2, 1], [2, 2], [1, 2]]}],
        engine="paddle",
        page=1,
    )

    with patch(
        "app.document_processing.ocr.paddle_ocr.paddle_available", return_value=True
    ), patch(
        "app.document_processing.ocr.paddle_ocr.ocr_pil_image_detailed_paddle",
        return_value=paddle_ok,
    ):
        from app.document_processing.ocr.strategy import ocr_pil_image_detailed

        img = Image.open(_make_text_image(tmp_path))
        out = ocr_pil_image_detailed(img, page_number=1)
        assert out.engine == "paddle"
        assert "CIL" in out.text
        assert out.boxes

    config_mod.get_settings.cache_clear()


def test_native_pdf_still_skips_ocr(digital_pdf, monkeypatch):
    monkeypatch.setenv("OCR_ENGINE", "paddle")
    from app import config as config_mod
    from app.document_processing.pdf_processor import process_pdf

    config_mod.get_settings.cache_clear()
    with patch("app.document_processing.pdf_processor.ocr_pdf_pages") as ocr_mock:
        result = process_pdf(digital_pdf)
        assert result.is_scanned is False
        assert result.ocr_used is False
        ocr_mock.assert_not_called()
    config_mod.get_settings.cache_clear()


def test_scanned_ocr_meta_preserves_engine_and_confidence(monkeypatch, tmp_path):
    """Page content_meta must carry OCR engine + confidence for SIH evidence."""
    monkeypatch.setenv("OCR_ENGINE", "tesseract")
    monkeypatch.setenv("OCR_FALLBACK", "none")
    from app import config as config_mod

    config_mod.get_settings.cache_clear()

    fake = OCRResult(
        text="NLCIL lignite 23.68 MT and CIL coal 85.81 MT",
        mean_confidence=81.5,
        word_count=8,
        engine="tesseract",
        page=1,
        boxes=[{"text": "NLCIL", "confidence": 80.0}],
    )
    import fitz

    pdf_path = tmp_path / "scanned_like.pdf"
    # Build a near-empty text PDF so density triggers OCR path
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "x", fontsize=8)  # tiny text → scanned by threshold
    doc.save(pdf_path)
    doc.close()

    with patch(
        "app.document_processing.pdf_processor.ocr_pil_image_detailed", return_value=fake
    ), patch(
        "app.document_processing.pdf_processor.looks_like_numeric_table", return_value=False
    ):
        # Force scanned by raising threshold temporarily
        monkeypatch.setenv("PDF_DIGITAL_TEXT_THRESHOLD", "10000")
        config_mod.get_settings.cache_clear()
        from app.document_processing.pdf_processor import process_pdf

        result = process_pdf(pdf_path)
        assert result.ocr_used is True
        assert result.pages
        meta = result.pages[0].content_meta or {}
        assert meta.get("ocr_engine") == "tesseract"
        assert meta.get("ocr_mean_confidence") == 81.5
        assert "NLCIL" in result.pages[0].text and "CIL" in result.pages[0].text

    config_mod.get_settings.cache_clear()


def test_review_queue_still_lists_review_required_geo_after_ocr_wiring(client, db_session, admin_headers):
    """Regression: review_required geological facts must still appear in Review Queue."""
    from app.models import Document, GeologicalFact, IndexStatus

    doc = Document(
        filename="ocr_geo.pdf",
        original_filename="ocr_geo.pdf",
        file_path="/tmp/ocr_geo.pdf",
        file_type="pdf",
        status="extracted",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db_session.add(doc)
    db_session.flush()
    fact = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        metric_kind="resource_quantity",
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.55,
        source_page=3,
        original_value="4.2",
        original_unit="MT",
        original_extracted_value="4.2",
        evidence_text="Resource estimate 4.2 MT pending review.",
        seam_name="Seam Delta",
    )
    db_session.add(fact)
    db_session.commit()

    body = client.get("/api/reviews", headers=admin_headers).json()
    match = next((i for i in body["items"] if i.get("geological_fact_id") == fact.id), None)
    assert match is not None
    assert match["status"] == ReviewStatus.PENDING.value
    assert match["extracted_value"] == "4.2"
    assert match["page_number"] == 3


@pytest.mark.skipif(
    not Path(
        r"C:\Users\karth\Documents\original\4f9ccbf9-0b18-4708-8337-13feb278b9c9_ilovepdf_merged.pdf"
    ).is_file(),
    reason="source PDF not on disk",
)
def test_paddle_import_smoke_when_installed():
    """If paddleocr is installed, import path must work; otherwise skip via paddle_available."""
    from app.document_processing.ocr.paddle_ocr import paddle_available

    if not paddle_available():
        pytest.skip("paddleocr not installed in this environment")
    import paddleocr  # noqa: F401

    assert paddle_available() is True
