"""Analytics semantic dimensions — Entity / Commodity / Metric / Measure separation."""

from __future__ import annotations

from app.analytics.dimensions import (
    classify_raw_metric,
    storage_metrics_for,
)
from app.analytics.service import list_dimensions, query_analytics_data, year_wise_trend
from app.models import DocumentChunk
from tests.test_phase6_analytics_topics import _seed_fact, _upload
import shutil
from pathlib import Path


def test_classify_coal_is_commodity_not_metric():
    cls = classify_raw_metric("coal", measurement_type="during")
    assert cls["commodity"] == "coal"
    assert cls["metric"] == "production"
    assert cls["measure"] == "during"
    assert cls["storage_metric"] == "coal"


def test_classify_production_target_is_measure_target():
    cls = classify_raw_metric("production_target")
    assert cls["metric"] == "production"
    assert cls["measure"] == "target"
    assert cls["commodity"] is None


def test_storage_metrics_coal_production():
    assert "coal" in storage_metrics_for(commodity="Coal", metric="production")
    assert "production" in storage_metrics_for(commodity="coal", metric="production")


def test_dimensions_separate_commodity_and_metric(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "Dims.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    db_session.add(
        DocumentChunk(
            document_id=doc_id,
            chunk_index=0,
            content="structured",
            content_type="structured_fact",
            page_number=5,
            document_name="Dims.pdf",
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
                "confidence": 0.95,
            },
        )
    )
    _seed_fact(
        db_session,
        doc_id,
        field_name="production",
        value="5.0",
        numeric_value=5.0,
        financial_year="FY2024",
        entity_name="Mine B",
    )
    db_session.commit()

    dims = list_dimensions(db_session)
    assert "Mine B" in dims["entities"]
    assert "coal" in dims["commodities"]
    assert "production" in dims["semantic_metrics"] or "production" in dims["metrics"]
    # Coal must not be the only way to express production — semantic metric exists
    assert "production" in dims["metrics"] or "production" in dims["semantic_metrics"]

    # Dependent: entity Mine B → coal commodity available
    filtered = list_dimensions(db_session, entity="Mine B")
    assert "coal" in filtered["commodities"]

    trend = year_wise_trend(
        db_session, entity="Mine B", metric="production", commodity="coal", measurement_type="during"
    )
    assert not trend["insufficient"]
    assert any(abs(float(p["value"]) - 85.81) < 0.01 for p in trend["data"])

    data = query_analytics_data(
        db_session,
        entity="Mine B",
        commodity="coal",
        metric="production",
        measure="during",
    )
    assert data["table"]
    assert data["commodity"] == "coal"
    assert data["metric"] == "production"
    row = next(r for r in data["table"] if r["period"] == "FY2025")
    assert abs(float(row["actual"]) - 85.81) < 0.01
    assert row.get("document_id") == doc_id
    assert row.get("page") == 5
