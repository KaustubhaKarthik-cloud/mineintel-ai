"""Phase 3 — AI extraction, confidence, and human review tests (mocked LLM)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import fitz
import pytest
from openpyxl import Workbook

from app.ai_extraction.confidence import classify_status, score_fact
from app.ai_extraction.llm import LLMError, MockLLMProvider
from app.ai_extraction.schemas import LLMExtractionResponse, LLMFactDraft
from app.ai_extraction.validator import detect_achievement_discrepancy, validate_draft
from app.models import DocumentStatus, ExtractedFact, FactStatus, ReviewItem, ReviewStatus


@pytest.fixture()
def annual_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "Annual_Report_2024.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # Use page 1 in fixture; evidence will cite page 1 (not 42) for realism in short PDF
    page.insert_text(
        (72, 72),
        "Mine B produced 3.9 MT during FY2024 against a target of 5.0 MT. "
        "Achievement of 82% was reported by operations.",
        fontsize=11,
    )
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def ocr_like_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "noisy_ocr.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Pr0ducti0n: 3.9 M? unclear scan quality.", fontsize=11)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def production_xlsx(tmp_path: Path) -> Path:
    path = tmp_path / "Production.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "FY2024"
    ws.append(["Mine", "Production", "Target"])
    ws.append(["Mine B", "3.9", "5.0"])
    wb.save(path)
    return path


def _upload(client, path: Path, name: str, mime: str):
    with path.open("rb") as f:
        return client.post(
            "/api/documents/upload",
            files={"file": (name, f, mime)},
            data={"mine_name": "Mine B", "document_category": "Production Report"},
        )


def test_extraction_from_digital_pdf(client, annual_pdf: Path):
    up = _upload(client, annual_pdf, "Annual_Report_2024.pdf", "application/pdf")
    assert up.status_code == 200
    doc_id = up.json()["id"]
    assert up.json()["status"] == DocumentStatus.COMPLETED.value

    r = client.post(f"/api/documents/{doc_id}/extract")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job"]["status"] == "completed"
    assert body["job"]["facts_count"] >= 2
    fields = {f["field_name"] for f in body["facts"]}
    assert "production" in fields
    assert "production_target" in fields
    prod = next(f for f in body["facts"] if f["field_name"] == "production")
    assert prod["evidence_text"]
    assert prod["page_number"] is not None
    assert "3.9" in (prod["value"] or "")


def test_extraction_from_ocr_like_text(client, ocr_like_pdf: Path):
    up = _upload(client, ocr_like_pdf, "noisy_ocr.pdf", "application/pdf")
    doc_id = up.json()["id"]
    r = client.post(f"/api/documents/{doc_id}/extract")
    assert r.status_code == 200
    facts = r.json()["facts"]
    assert any(f["field_name"] == "production" for f in facts)
    prod = next(f for f in facts if f["field_name"] == "production")
    assert prod["status"] == FactStatus.REVIEW_REQUIRED.value
    assert prod["confidence_score"] < 0.85


def test_excel_extraction(client, production_xlsx: Path):
    up = _upload(
        client,
        production_xlsx,
        "Production.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    doc_id = up.json()["id"]
    r = client.post(f"/api/documents/{doc_id}/extract")
    assert r.status_code == 200
    facts = r.json()["facts"]
    assert any(f["field_name"] == "production" and f["sheet_name"] == "FY2024" for f in facts)


def test_json_validation_and_missing_fields():
    ok, warnings, num = validate_draft(
        LLMFactDraft(
            field="production",
            value=3.9,
            unit="MT",
            mine="Mine B",
            evidence="Mine B produced 3.9 MT",
            page_number=1,
        ),
        "Mine B produced 3.9 MT during FY2024",
    )
    assert ok and num == 3.9

    bad, warnings, _ = validate_draft(
        LLMFactDraft(field="production", value="abc", evidence="nope"),
        "unrelated",
    )
    assert bad is False


def test_confidence_and_thresholds():
    draft = LLMFactDraft(
        field="production",
        value=3.9,
        unit="MT",
        mine="Mine B",
        financial_year="FY2024",
        evidence="Mine B produced 3.9 MT during FY2024",
    )
    high = score_fact(draft, is_ocr_source=False, schema_ok=True, evidence_in_text=True)
    assert high >= 0.7
    assert classify_status(0.96) == "high_confidence"
    assert classify_status(0.41) == "review_required"


def test_low_confidence_creates_review(client, ocr_like_pdf: Path, db_session, admin_headers):
    up = _upload(client, ocr_like_pdf, "noisy_ocr.pdf", "application/pdf")
    doc_id = up.json()["id"]
    client.post(f"/api/documents/{doc_id}/extract")
    reviews = client.get("/api/reviews", headers=admin_headers).json()
    assert reviews["pending"] >= 1
    assert any(i["document_id"] == doc_id for i in reviews["items"])


def test_human_approve_correct_reject(client, annual_pdf: Path, db_session, admin_headers):
    # Force review by lowering confidence via ambiguous OCR-like provider response
    class LowConfProvider(MockLLMProvider):
        def extract_structured_information(self, document_name, pages):
            return LLMExtractionResponse(
                entities=["Mine B"],
                facts=[
                    LLMFactDraft(
                        field="production",
                        value=3.9,
                        unit="MT",
                        mine="Mine B",
                        financial_year="FY2024",
                        page_number=pages[0]["page_number"],
                        evidence="Mine B produced 3.9 MT during FY2024",
                        ambiguous=True,
                    ),
                    LLMFactDraft(
                        field="production_target",
                        value=5.0,
                        unit="MT",
                        mine="Mine B",
                        financial_year="FY2024",
                        page_number=pages[0]["page_number"],
                        evidence="against a target of 5.0 MT",
                        ambiguous=True,
                    ),
                ],
                warnings=[],
            )

    up = _upload(client, annual_pdf, "Annual_Report_2024.pdf", "application/pdf")
    doc_id = up.json()["id"]
    with patch("app.ai_extraction.service.get_llm_provider", return_value=LowConfProvider()):
        ext = client.post(f"/api/documents/{doc_id}/extract")
    assert ext.status_code == 200, ext.text
    assert ext.json()["job"]["review_count"] >= 1

    items = [i for i in client.get("/api/reviews", headers=admin_headers).json()["items"] if i["document_id"] == doc_id and i["status"] == "pending"]
    assert len(items) >= 1
    a = items[0]
    b = items[1] if len(items) > 1 else items[0]

    ok = client.post(f"/api/reviews/{a['id']}/approve", headers=admin_headers)
    assert ok.status_code == 200
    assert ok.json()["status"] == "approved"

    corr = client.post(
        f"/api/reviews/{b['id']}/correct",
        headers=admin_headers,
        json={
            "action": "correct",
            "corrected_value": "4.0",
            "corrected_unit": "MT",
            "review_notes": "Verified against annexure",
            "reviewer": "reviewer.mehta",
        },
    )
    assert corr.status_code == 200
    assert corr.json()["status"] == "corrected"
    assert corr.json()["corrected_value"] == "4.0"
    assert corr.json()["extracted_value"] == b["extracted_value"]  # original preserved

    fact = db_session.query(ExtractedFact).filter(ExtractedFact.id == b["extracted_fact_id"]).one()
    assert fact.status == FactStatus.CORRECTED.value
    assert fact.meta and fact.meta.get("original_ai_value") == b["extracted_value"]
    assert fact.meta.get("correction_history")


def test_reported_vs_calculated_discrepancy(client, annual_pdf: Path, db_session):
    up = _upload(client, annual_pdf, "Annual_Report_2024.pdf", "application/pdf")
    doc_id = up.json()["id"]
    r = client.post(f"/api/documents/{doc_id}/extract")
    facts = r.json()["facts"]
    calc = [f for f in facts if f["field_name"] == "achievement_percentage_calculated"]
    reported = [f for f in facts if f["field_name"] == "achievement_percentage" and not f["is_calculated"]]
    assert calc, "expected calculated achievement"
    assert reported, "expected reported achievement"
    assert calc[0]["is_calculated"] is True
    # 3.9/5.0 = 78% vs reported 82%
    assert abs(float(calc[0]["value"]) - 78.0) < 0.1
    assert any("differs" in (w or "").lower() for w in (reported[0].get("warnings") or []) + (r.json()["job"].get("warnings") or []))


def test_llm_failure_and_invalid_response(client, annual_pdf: Path):
    up = _upload(client, annual_pdf, "Annual_Report_2024.pdf", "application/pdf")
    doc_id = up.json()["id"]

    class Boom(MockLLMProvider):
        def extract_structured_information(self, document_name, pages):
            raise LLMError("LLM provider request failed.")

    with patch("app.ai_extraction.service.get_llm_provider", return_value=Boom()):
        r = client.post(f"/api/documents/{doc_id}/extract")
    assert r.status_code == 400
    assert "LLM" in r.json()["detail"] or "failed" in r.json()["detail"].lower()


def test_source_traceability(client, annual_pdf: Path):
    up = _upload(client, annual_pdf, "Annual_Report_2024.pdf", "application/pdf")
    doc_id = up.json()["id"]
    facts = client.post(f"/api/documents/{doc_id}/extract").json()["facts"]
    for f in facts:
        if f["is_calculated"]:
            continue
        assert f["evidence_text"]
        assert f["page_number"] is not None or f["sheet_name"]


def test_phase2_still_works_after_phase3(client, annual_pdf: Path):
    up = _upload(client, annual_pdf, "Annual_Report_2024.pdf", "application/pdf")
    assert up.status_code == 200
    detail = client.get(f"/api/documents/{up.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["page_count"] >= 1
    assert len(detail.json()["pages"]) >= 1


def test_detect_discrepancy_unit():
    calc, warn = detect_achievement_discrepancy(3.9, 5.0, 82.0)
    assert calc == 78.0
    assert warn and "differs" in warn.lower()
    calc2, warn2 = detect_achievement_discrepancy(3.9, 5.0, 78.0)
    assert warn2 is None
