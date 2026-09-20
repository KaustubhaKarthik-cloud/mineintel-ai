"""End-to-end audit coverage for Phases 1–5 (user numbering).

Internal module names differ slightly (code: retrieval=Phase4, validation=Phase5,
assistant=Phase6) — this file validates the pipeline the product requires before
any further Phase-6 work.
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ai_extraction.confidence import score_fact
from app.ai_extraction.schemas import LLMFactDraft
from app.document_processing.ocr_refine import digits_confusable, merge_ocr_decimals
from app.document_processing.pdf_processor import ocr_pdf_pages, process_pdf
from app.models import ExtractedFact, FactStatus, SourceType
from app.assistant.query_router import parse_query, resolve_route
from app.validation.comparator import compare_numeric
from app.validation.rules import normalize_field, normalize_period


ILOVE_PDF = Path(
    r"C:\Users\karth\Documents\original\4f9ccbf9-0b18-4708-8337-13feb278b9c9_ilovepdf_merged.pdf"
)


def _upload(client, path: Path, name: str | None = None, mime: str = "application/pdf"):
    with path.open("rb") as f:
        return client.post(
            "/api/documents/upload",
            files={"file": (name or path.name, f, mime)},
            data={"mine_name": "Mine B"},
        )


# ---------------------------------------------------------------------------
# Phase 1 — foundation
# ---------------------------------------------------------------------------


def test_phase1_health_and_docs(client):
    h = client.get("/api/health")
    assert h.status_code == 200
    assert h.json()["status"] == "ok"
    docs = client.get("/api/documents")
    assert docs.status_code == 200


# ---------------------------------------------------------------------------
# Phase 2 — ingestion formats + provenance
# ---------------------------------------------------------------------------


def test_phase2_digital_pdf_provenance(client, digital_pdf):
    r = _upload(client, digital_pdf)
    assert r.status_code == 200
    body = r.json()
    assert body["file_type"] == "pdf"
    assert body["page_count"] >= 2
    for p in body["pages"]:
        assert p["page_number"] >= 1
        assert p["source_type"] == SourceType.PDF_PAGE.value
        assert p.get("source_location")


def test_phase2_excel_provenance(client, production_xlsx):
    r = _upload(
        client,
        production_xlsx,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file_type"] in {"excel", "xlsx", "xls"}
    assert body["pages"]
    assert any(p.get("sheet_name") for p in body["pages"])
    assert all(p["source_type"] == SourceType.EXCEL_SHEET.value for p in body["pages"])


def test_phase2_png_jpg_ocr(client, tmp_path):
    for fmt, name, mime in (
        ("PNG", "scan.png", "image/png"),
        ("JPEG", "scan.jpg", "image/jpeg"),
    ):
        img = Image.new("RGB", (640, 200), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((20, 80), "Mine B inspection OK FY2024", fill=(0, 0, 0))
        path = tmp_path / name
        img.save(path, format=fmt)
        r = _upload(client, path, mime=mime)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ocr_completed"] is True or body["is_scanned"] is True
        assert body["pages"]
        assert all(p["source_type"] in {SourceType.OCR_PAGE.value, SourceType.IMAGE.value} for p in body["pages"])


# ---------------------------------------------------------------------------
# OCR quality — general refine (no document-specific value swap)
# ---------------------------------------------------------------------------


def test_ocr_neighbor_consensus_refine_is_general():
    """Confusable digit pairs corrected only with shared numeric neighbors."""
    assert digits_confusable("25.68", "23.68")
    assert not digits_confusable("151.24", "167.13")
    base = "Actual 151.24 25.68 12.64 Target 167.13 26.50 12.00"
    detail = "Actual 151.24 23.68 12.64 other 99.99"
    merged = merge_ocr_decimals(base, detail)
    assert "23.68" in merged and "25.68" not in merged
    # Without neighbor consensus, confusable tokens must not flip
    lone = merge_ocr_decimals("value 25.68 alone", "noise 23.68 alone")
    assert "25.68" in lone


@pytest.mark.skipif(not ILOVE_PDF.is_file(), reason="source PDF not on disk")
def test_ilovepdf_page2_source_and_ocr_pipeline():
    """Visual-source audit: page-2 Actual lignite is 23.68; pipeline must not keep 25.68."""
    # Selectable text layer is empty (scanned)
    doc = fitz.open(ILOVE_PDF)
    page = doc[1]
    digital = (page.get_text("text") or "").strip()
    doc.close()
    assert digital == "" or "23.68" not in digital  # no reliable text layer

    pages = ocr_pdf_pages(ILOVE_PDF, dpi=200, detail_dpi=300, refine=True)
    assert len(pages) >= 2
    p2 = pages[1]
    assert p2.content_meta is not None
    assert "ocr_mean_confidence" in p2.content_meta
    # After refine, the corrected lignite actual must appear; the misread must not.
    assert "23.68" in p2.text
    assert "25.68" not in p2.text
    assert "151.24" in p2.text and "167.13" in p2.text and "26.50" in p2.text


# ---------------------------------------------------------------------------
# Phase 3 — confidence + OCR caution
# ---------------------------------------------------------------------------


def test_phase3_low_ocr_confidence_forces_review():
    draft = LLMFactDraft(
        field="lignite",
        value="25.68",
        unit="MT",
        mine="NLCIL",
        financial_year="FY2023-24",
        evidence="Lignite actual 25.68 MT",
        page_number=2,
    )
    conf = score_fact(
        draft,
        is_ocr_source=True,
        schema_ok=True,
        evidence_in_text=True,
        ocr_mean_confidence=55.0,
        ocr_low_confidence_decimals=["25.68"],
    )
    assert conf < 0.85


# ---------------------------------------------------------------------------
# Phase 4 (user) / code Phase 5 — validation matching
# ---------------------------------------------------------------------------


def test_phase4_unit_and_period_normalization():
    assert normalize_field("Annual Production") == "production"
    assert normalize_period("FY2023-24") == "FY2023-24"
    cmp = compare_numeric(5.2, "MT", 5.2, "MT")
    assert cmp.equal is True
    # tonnes/day vs bare tonnes should not silently equal
    rate = compare_numeric(100.0, "tonnes/day", 100.0, "tonnes")
    assert rate.equal is False or rate.unit_review or rate.incompatible_units


# ---------------------------------------------------------------------------
# Phase 5 (user) — routing evidence-aware + hallucination
# ---------------------------------------------------------------------------


def test_phase5_routing_no_entity_dump(db_session, client, digital_pdf, tmp_path):
    path = tmp_path / "Ops.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    db_session.add(
        ExtractedFact(
            document_id=doc_id,
            field_name="production",
            value="5.2",
            numeric_value=5.2,
            unit="MT",
            entity_name="Mine B",
            financial_year="FY2024",
            evidence_text="5.2",
            confidence_score=0.95,
            status=FactStatus.HIGH_CONFIDENCE.value,
        )
    )
    db_session.commit()
    q = "What are the actual overburden and lignite production figures for FY2023-24?"
    plan = resolve_route(db_session, parse_query(q))
    assert plan.query_type != "structured"


def test_phase5_hallucination_guard(client, digital_pdf):
    _upload(client, digital_pdf)
    r = client.post(
        "/api/assistant/query",
        json={"question": "What is the uranium grade on Mars mine ZZZ-999?"},
    )
    assert r.status_code == 200
    body = r.json()
    reply = (body.get("reply") or "").lower()
    assert (
        "sufficient" in reply
        or body.get("warnings")
        or not body.get("structured_evidence")
    )
    assert "18.4" not in (body.get("reply") or "")


def test_phase5_unseen_entity_routing(db_session, client, digital_pdf, tmp_path):
    path = tmp_path / "Alpha.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    db_session.add(
        ExtractedFact(
            document_id=doc_id,
            field_name="overburden",
            value="12.4",
            numeric_value=12.4,
            unit="Mm3",
            entity_name="Quarry Alpha",
            financial_year="FY2024",
            evidence_text="12.4",
            confidence_score=0.95,
            status=FactStatus.HIGH_CONFIDENCE.value,
        )
    )
    db_session.commit()
    hit = resolve_route(db_session, parse_query("What was Quarry Alpha's overburden in FY2024?"))
    miss = resolve_route(
        db_session, parse_query("What are the actual overburden figures for FY2024 for Basin West?")
    )
    assert hit.query_type == "structured"
    assert miss.query_type != "structured"
