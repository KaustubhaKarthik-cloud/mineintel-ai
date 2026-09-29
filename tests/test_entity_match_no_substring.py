"""Entity filter must not use broad substring matching (CIL ↛ NLCIL)."""

from __future__ import annotations

from app.analytics.geological_adapter import query_geological_analytics_data
from app.analytics.service import year_wise_trend
from app.models import Document, DocumentChunk, FactStatus, GeologicalFact, IndexStatus


def test_production_entity_filter_exact_not_substring(db_session):
    doc = Document(
        filename="ent.pdf",
        original_filename="ent.pdf",
        file_path="/tmp/ent.pdf",
        file_type="pdf",
        status="extracted",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db_session.add(doc)
    db_session.flush()
    for entity, value in (("CIL", 10.0), ("NLCIL", 20.0)):
        db_session.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=0 if entity == "CIL" else 1,
                content="structured",
                content_type="structured_fact",
                page_number=1,
                document_name="ent.pdf",
                is_active=True,
                meta={
                    "structured_fact": True,
                    "entity": entity,
                    "metric": "production",
                    "fiscal_year": "FY2025",
                    "measurement_type": "during",
                    "value": value,
                    "unit": "MT",
                    "page": 1,
                    "confidence": 0.95,
                },
            )
        )
    db_session.commit()

    trend_cil = year_wise_trend(
        db_session, entity="CIL", metric="production", measurement_type="during"
    )
    assert not trend_cil["insufficient"]
    assert all(abs(float(p["value"]) - 10.0) < 0.01 for p in trend_cil["data"])

    trend_nl = year_wise_trend(
        db_session, entity="NLCIL", metric="production", measurement_type="during"
    )
    assert not trend_nl["insufficient"]
    assert all(abs(float(p["value"]) - 20.0) < 0.01 for p in trend_nl["data"])


def test_geological_entity_filter_exact(db_session):
    ids = []
    for name in ("CIL Block", "NLCIL Block"):
        d = Document(
            filename=f"{name}.pdf",
            original_filename=f"{name}.pdf",
            file_path=f"/tmp/{name}.pdf",
            file_type="pdf",
            status="extracted",
            index_status=IndexStatus.INDEXED.value,
            mine_name=name,
            version=1,
        )
        db_session.add(d)
        db_session.flush()
        ids.append(d.id)
        db_session.add(
            GeologicalFact(
                document_id=d.id,
                domain="geological",
                metric_kind="formation",
                geological_formation="Barakar Formation",
                evidence_text="Barakar Formation",
                source_page=1,
                status=FactStatus.HIGH_CONFIDENCE.value,
                extraction_confidence=0.9,
            )
        )
    db_session.commit()

    data = query_geological_analytics_data(
        db_session, document_ids=ids, entity="CIL Block"
    )
    assert not data.get("insufficient")
    assert all((r.get("entity") or "") == "CIL Block" for r in data.get("items") or [])
    assert not any("NLCIL" in (r.get("entity") or "") for r in data.get("items") or [])
