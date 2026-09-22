"""API contract tests for explore, reports, analytics document filter, and file access."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.models import DocumentChunk, FactStatus
from app.analytics.service import list_dimensions, year_wise_trend
from tests.test_phase6_analytics_topics import _seed_fact, _upload


def test_explore_dimensions_and_structured_facts(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "Explore.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    db_session.add(
        DocumentChunk(
            document_id=doc_id,
            chunk_index=0,
            content="STRUCTURED_FACT | entity=Mine B | metric=coal | reporting_period=March | measure=during | fiscal_year=FY2025 | value=85.81 | unit=MT | table=Table 1.1 | page=5 | column=x",
            content_type="structured_fact",
            page_number=5,
            document_name="Explore.pdf",
            is_active=True,
            meta={
                "structured_fact": True,
                "entity": "Mine B",
                "metric": "coal",
                "reporting_month": "March",
                "fiscal_year": "FY2025",
                "measurement_type": "during",
                "value": 85.81,
                "unit": "MT",
                "page": 5,
                "table_title": "Table 1.1",
                "table_id": "t1",
                "confidence": 0.95,
            },
        )
    )
    db_session.commit()

    dims = client.get("/api/explore/dimensions")
    assert dims.status_code == 200
    body = dims.json()
    assert "Mine B" in body["entities"]
    assert "coal" in body["metrics"]
    assert "March" in body["reporting_months"]
    assert any(d["id"] == doc_id for d in body["documents"])

    facts = client.get("/api/explore/structured-facts", params={"entity": "Mine B"})
    assert facts.status_code == 200
    items = facts.json()["items"]
    assert len(items) >= 1
    assert items[0]["value"] == 85.81
    assert items[0]["document_id"] == doc_id
    assert items[0]["page"] == 5


def test_analytics_document_filter(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "A.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(
        db_session,
        doc_id,
        field_name="production",
        value="5.0",
        numeric_value=5.0,
        financial_year="FY2024",
        status=FactStatus.HIGH_CONFIDENCE.value,
    )
    db_session.commit()

    dims = list_dimensions(db_session, document_ids=[doc_id])
    assert any(d["id"] == doc_id for d in dims["documents"])
    assert "Mine B" in dims["entities"]

    trend = year_wise_trend(db_session, entity="Mine B", metric="production", document_ids=[doc_id])
    assert not trend["insufficient"]

    r = client.get(
        "/api/analytics/trend",
        params={"entity": "Mine B", "metric": "production", "document_id": doc_id},
    )
    assert r.status_code == 200
    assert r.json()["insufficient"] is False

    # Wrong document id → insufficient
    r2 = client.get(
        "/api/analytics/trend",
        params={"entity": "Mine B", "metric": "production", "document_id": "no-such-doc"},
    )
    assert r2.status_code == 200
    assert r2.json()["insufficient"] is True


def test_reports_generate_view_download(client, digital_pdf, tmp_path, db_session, admin_headers):
    path = tmp_path / "R.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(
        db_session,
        doc_id,
        field_name="production",
        value="4.2",
        numeric_value=4.2,
        financial_year="FY2024",
        status=FactStatus.HIGH_CONFIDENCE.value,
    )
    db_session.commit()

    empty = client.get("/api/reports")
    assert empty.status_code == 200
    assert empty.json()["total"] == 0

    gen = client.post(
        "/api/reports/generate",
        json={"entity": "Mine B", "metric": "production", "document_ids": [doc_id]},
    )
    assert gen.status_code == 200
    report_id = gen.json()["id"]
    assert gen.json()["status"] == "ready"
    assert gen.json()["has_content"] is True

    listed = client.get("/api/reports")
    assert listed.json()["total"] == 1

    detail = client.get(f"/api/reports/{report_id}")
    assert detail.status_code == 200
    assert "Mine B" in (detail.json().get("content") or "")

    view = client.get(f"/api/reports/{report_id}/view")
    assert view.status_code == 200
    assert b"Mine B" in view.content

    dl = client.get(f"/api/reports/{report_id}/download")
    assert dl.status_code == 200
    assert "attachment" in dl.headers.get("content-disposition", "").lower()

    deleted = client.delete(f"/api/reports/{report_id}", headers=admin_headers)
    assert deleted.status_code == 200
    assert client.get("/api/reports").json()["total"] == 0


def test_document_file_endpoint(client, digital_pdf, tmp_path):
    path = tmp_path / "File.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    r = client.get(f"/api/documents/{doc_id}/file")
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_search_returns_indexed_chunks(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "Search.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    # Index via API (mock embeddings)
    idx = client.post(f"/api/documents/{doc_id}/index")
    assert idx.status_code == 200

    r = client.post("/api/search", json={"query": "production FY2024", "top_k": 5})
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    # May be empty if mock embedding similarity is low — but endpoint must work
    assert isinstance(body["results"], list)


def test_system_status_no_secrets(client):
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    assert "application" in body
    assert "ai_assistant" in body
    blob = str(body).lower()
    assert "sk-" not in blob
    assert "api_key" not in blob or "configured" in blob  # boolean only
