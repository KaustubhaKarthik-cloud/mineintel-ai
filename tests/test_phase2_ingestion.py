"""Phase 2 — document ingestion, OCR, and page-level storage tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.document_processing.pdf_processor import extract_digital_pdf, process_pdf
from app.document_processing.excel_processor import process_excel
from app.document_processing.types import ExtractedPage, ProcessingResult
from app.models import Document, DocumentPage, DocumentStatus, SourceType


def test_health_still_works(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_valid_pdf_upload(client, digital_pdf: Path):
    with digital_pdf.open("rb") as f:
        r = client.post(
            "/api/documents/upload",
            files={"file": ("Annual_Report_2024.pdf", f, "application/pdf")},
            data={"mine_name": "Mine B", "document_category": "Production Report"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == DocumentStatus.COMPLETED.value
    assert body["file_type"] == "pdf"
    assert body["page_count"] >= 2
    assert any("3.9 MT" in (p["text"] or "") for p in body["pages"])
    assert all(p["source_type"] == SourceType.PDF_PAGE.value for p in body["pages"])


def test_invalid_file_type(client, tmp_path: Path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not allowed")
    with bad.open("rb") as f:
        r = client.post(
            "/api/documents/upload",
            files={"file": ("notes.txt", f, "text/plain")},
        )
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


def test_digital_pdf_extraction(digital_pdf: Path):
    pages = extract_digital_pdf(digital_pdf)
    assert len(pages) == 3
    assert pages[1].page_number == 2
    assert "Mine B produced 3.9 MT" in pages[1].text
    result = process_pdf(digital_pdf)
    assert result.is_scanned is False
    assert result.ocr_used is False


def test_scanned_pdf_ocr(client, scanned_pdf: Path):
    fake = ProcessingResult(
        pages=[
            ExtractedPage(
                page_number=1,
                text="Scanned Inspection: Mine B safety checklist OK",
                source_type=SourceType.OCR_PAGE.value,
                source_location="page:1:ocr",
            )
        ],
        is_scanned=True,
        ocr_used=True,
        file_type="pdf",
        page_count=1,
        meta={"mode": "scanned_ocr"},
    )
    with patch("app.document_processing.service.process_pdf", return_value=fake):
        with scanned_pdf.open("rb") as f:
            r = client.post(
                "/api/documents/upload",
                files={"file": ("Scanned_Inspection.pdf", f, "application/pdf")},
            )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == DocumentStatus.COMPLETED.value
    assert body["is_scanned"] is True
    assert body["ocr_completed"] is True
    assert "Mine B" in body["pages"][0]["text"]


def test_excel_processing(client, production_xlsx: Path):
    with production_xlsx.open("rb") as f:
        r = client.post(
            "/api/documents/upload",
            files={
                "file": (
                    "Production.xlsx",
                    f,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == DocumentStatus.COMPLETED.value
    assert body["file_type"] == "excel"
    assert body["page_count"] == 1
    page = body["pages"][0]
    assert page["source_type"] == SourceType.EXCEL_SHEET.value
    assert page["sheet_name"] == "FY2024"
    assert "Mine B" in page["text"]
    assert "3.9" in page["text"]


def test_excel_processor_unit(production_xlsx: Path):
    result = process_excel(production_xlsx)
    assert result.page_count == 1
    assert result.pages[0].sheet_name == "FY2024"
    assert result.pages[0].content_meta is not None
    assert "Mine" in result.pages[0].content_meta["columns"]


def test_image_ocr(client, sample_png: Path):
    from app.document_processing.ocr_processor import OCRResult

    fake = OCRResult(
        text="Mine B produced 3.9 MT in FY2024",
        mean_confidence=90.0,
        word_count=6,
        engine="tesseract",
        page=1,
    )
    with patch(
        "app.document_processing.image_processor.ocr_pil_image_detailed",
        return_value=fake,
    ):
        with sample_png.open("rb") as f:
            r = client.post(
                "/api/documents/upload",
                files={"file": ("inspection.png", f, "image/png")},
            )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == DocumentStatus.COMPLETED.value
    assert body["file_type"] == "image"
    assert body["pages"][0]["page_number"] == 1
    assert body["pages"][0]["source_type"] == SourceType.IMAGE.value
    assert "3.9 MT" in body["pages"][0]["text"]


def test_page_level_text_storage(client, digital_pdf: Path, db_session):
    with digital_pdf.open("rb") as f:
        r = client.post(
            "/api/documents/upload",
            files={"file": ("Annual_Report_2024.pdf", f, "application/pdf")},
        )
    assert r.status_code == 200
    doc_id = r.json()["id"]
    pages = db_session.query(DocumentPage).filter(DocumentPage.document_id == doc_id).all()
    assert len(pages) >= 2
    assert {p.page_number for p in pages} == set(range(1, len(pages) + 1))
    detail = client.get(f"/api/documents/{doc_id}")
    assert detail.status_code == 200
    assert len(detail.json()["pages"]) == len(pages)


def test_processing_failure_handling(client, digital_pdf: Path):
    with patch(
        "app.document_processing.service.process_file",
        side_effect=RuntimeError("boom"),
    ):
        with digital_pdf.open("rb") as f:
            r = client.post(
                "/api/documents/upload",
                files={"file": ("Annual_Report_2024.pdf", f, "application/pdf")},
            )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == DocumentStatus.FAILED.value
    assert body["error_message"]
    assert "boom" not in (body["error_message"] or "")  # no raw internals to UI path
    assert "Processing failed" in body["error_message"]


def test_list_documents_from_db(client, digital_pdf: Path, production_xlsx: Path):
    for path, name, mime in [
        (digital_pdf, "Annual_Report_2024.pdf", "application/pdf"),
        (
            production_xlsx,
            "Production.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ]:
        with path.open("rb") as f:
            assert client.post(
                "/api/documents/upload",
                files={"file": (name, f, mime)},
            ).status_code == 200

    r = client.get("/api/documents")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_path_traversal_filename_sanitized(client, digital_pdf: Path, db_session):
    with digital_pdf.open("rb") as f:
        r = client.post(
            "/api/documents/upload",
            files={"file": ("../../evil_Annual_Report_2024.pdf", f, "application/pdf")},
        )
    assert r.status_code == 200
    doc = db_session.query(Document).first()
    assert doc is not None
    assert ".." not in doc.filename
    assert Path(doc.file_path).name == doc.filename
