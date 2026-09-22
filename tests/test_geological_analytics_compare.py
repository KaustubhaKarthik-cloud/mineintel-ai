"""Geological Analytics adapter + Document Comparison semantic fixes."""

from __future__ import annotations

from app.analytics.index_facts import list_analytics_documents
from app.analytics.service import list_dimensions, query_analytics_data
from app.geology.classifier import classify_document_text
from app.geology.explorer import list_geological_documents
from app.geology.geo_analytics import compare_documents
from app.geology.metric_kinds import (
    BOREHOLE_DEPTH,
    MINIMUM_WORKABLE_SEAM_THICKNESS,
    RESOURCE_QUANTITY,
)
from app.geology.semantic import (
    NO_COMPATIBLE_STRUCTURED,
    NO_STRUCTURED_GEOLOGICAL,
    geo_metrics_compatible,
    normalize_geo_metric,
)
from app.geology.taxonomy import DocumentDomain
from app.models import Document, FactStatus, GeologicalFact, IndexStatus


SHEETALDHARA_SNIPPET = """
Geological exploration report — West of Sheetaldhara Block
Barakar Formation. Seam R4 resource 1.67 MT.
Minimum workable thickness considered = 0.90 m (page 28).
Borehole BH-12 drilled to 214.5 m.
"""


def _doc(db, name: str, *, mine: str | None = None) -> Document:
    d = Document(
        filename=name,
        original_filename=name,
        file_path=f"/tmp/{name}",
        file_type="pdf",
        status="extracted",
        index_status=IndexStatus.INDEXED.value,
        document_category="Geological Exploration Report",
        mine_name=mine,
        version=1,
        meta={
            "g1_classification": {
                "domain": "geological_exploration",
                "label": "Geological Exploration Report",
                "confidence": 0.95,
            }
        },
    )
    db.add(d)
    db.flush()
    return d


def _fact(db, doc: Document, **kwargs) -> GeologicalFact:
    defaults = {
        "document_id": doc.id,
        "domain": "geological",
        "status": FactStatus.HIGH_CONFIDENCE.value,
        "extraction_confidence": 0.9,
        "source_page": 1,
        "evidence_text": "structured geological evidence",
    }
    defaults.update(kwargs)
    row = GeologicalFact(**defaults)
    db.add(row)
    db.flush()
    return row


def test_sheetaldhara_detected_as_geological_exploration():
    result = classify_document_text(
        SHEETALDHARA_SNIPPET, filename_hint="West_of_Sheetaldhara.pdf"
    )
    assert result.domain == DocumentDomain.GEOLOGICAL_EXPLORATION.value


def test_zero_extracted_fact_does_not_mean_zero_geological(db_session):
    doc = _doc(db_session, "West_of_Sheetaldhara.pdf", mine="West of Sheetaldhara")
    _fact(
        db_session,
        doc,
        metric_kind=MINIMUM_WORKABLE_SEAM_THICKNESS,
        thickness="0.90",
        thickness_unit="m",
        thickness_normalized_m=0.9,
        source_page=28,
        evidence_text="Minimum workable thickness = 0.90 m",
    )
    db_session.commit()

    docs = list_analytics_documents(db_session)
    match = next(d for d in docs if d["id"] == doc.id)
    assert match["production_fact_count"] == 0
    assert match["geological_fact_count"] >= 1
    assert match["has_structured_data"] is True
    assert match["domain"] == "geological"


def test_geological_analytics_discovers_structured_facts(db_session):
    doc = _doc(db_session, "West_of_Sheetaldhara.pdf", mine="West of Sheetaldhara")
    _fact(
        db_session,
        doc,
        metric_kind="minimum workable thickness",  # alias form
        thickness="0.90",
        thickness_unit="m",
        thickness_normalized_m=0.9,
        source_page=28,
        evidence_text="Minimum workable thickness = 0.90 m",
    )
    _fact(
        db_session,
        doc,
        metric_kind="seam resource",
        seam_name="R4",
        original_value="1.67",
        original_unit="MT",
        source_page=31,
        evidence_text="Seam R4 resource = 1.67 MT",
    )
    db_session.commit()

    dims = list_dimensions(db_session, document_ids=[doc.id], domain="geological")
    assert dims["domain"] == "geological"
    assert dims["fact_count"] >= 1
    assert any(
        normalize_geo_metric(m) == MINIMUM_WORKABLE_SEAM_THICKNESS or m == MINIMUM_WORKABLE_SEAM_THICKNESS
        for m in dims["metrics"]
    )

    data = query_analytics_data(
        db_session,
        document_ids=[doc.id],
        domain="geological",
        metric="minimum workable thickness",
    )
    assert data["domain"] == "geological"
    assert not data.get("insufficient")
    assert data["table"]
    row = data["table"][0]
    assert row.get("page") == 28
    assert abs(float(row.get("actual")) - 0.90) < 0.001
    assert row.get("unit") == "m"
    assert row.get("document_id") == doc.id


def test_analytics_does_not_fabricate_from_rag_only(db_session):
    doc = _doc(db_session, "rag_only_geo.pdf")
    # Document exists but has zero GeologicalFact rows — only "would-be" RAG
    db_session.commit()

    data = query_analytics_data(db_session, document_ids=[doc.id], domain="geological")
    assert data["insufficient"] is True
    assert data["message"] == NO_STRUCTURED_GEOLOGICAL
    assert data["table"] == []


def test_review_required_preserved_in_analytics(db_session):
    doc = _doc(db_session, "review_geo.pdf")
    _fact(
        db_session,
        doc,
        metric_kind=MINIMUM_WORKABLE_SEAM_THICKNESS,
        thickness="0.90",
        thickness_unit="m",
        status=FactStatus.REVIEW_REQUIRED.value,
        source_page=28,
    )
    db_session.commit()

    data = query_analytics_data(db_session, document_ids=[doc.id], domain="geological")
    assert data["table"]
    assert data["table"][0]["status"] == FactStatus.REVIEW_REQUIRED.value
    assert data["table"][0]["requires_human_verification"] is True
    assert data["table"][0]["review_bucket"] == "review_required"


def test_document_selector_dedupes_by_document_id(db_session):
    a = _doc(db_session, "North_Parbelia_G3.pdf")
    b = _doc(db_session, "North_Parbelia_G3.pdf")  # same filename, different id
    _fact(db_session, a, metric_kind="formation", geological_formation="Barakar Formation")
    _fact(db_session, b, metric_kind="formation", geological_formation="Barakar Formation")
    # Simulate accidental duplicate listing risk: same id cannot appear twice
    db_session.commit()

    docs = list_geological_documents(db_session)
    ids = [d["document_id"] for d in docs]
    assert len(ids) == len(set(ids))
    names = [d for d in docs if d["document_name"] == "North_Parbelia_G3.pdf"]
    assert len(names) == 2  # different IDs kept separate
    assert names[0]["display_name"] != names[1]["display_name"] or names[0]["document_id"] != names[1]["document_id"]


def test_metric_aliases_normalize_consistently():
    assert normalize_geo_metric("minimum workable thickness") == MINIMUM_WORKABLE_SEAM_THICKNESS
    assert normalize_geo_metric("minimum_workable_seam_thickness") == MINIMUM_WORKABLE_SEAM_THICKNESS
    assert normalize_geo_metric("workable seam thickness") == MINIMUM_WORKABLE_SEAM_THICKNESS
    assert normalize_geo_metric("seam resource") == RESOURCE_QUANTITY
    assert normalize_geo_metric("coal resource") == RESOURCE_QUANTITY
    assert normalize_geo_metric("formations") == "formation"
    assert normalize_geo_metric("boreholes") == "borehole"
    assert normalize_geo_metric("borehole depth") == BOREHOLE_DEPTH


def test_thickness_not_compatible_with_resource():
    assert not geo_metrics_compatible(MINIMUM_WORKABLE_SEAM_THICKNESS, RESOURCE_QUANTITY)
    assert not geo_metrics_compatible(RESOURCE_QUANTITY, BOREHOLE_DEPTH)
    assert geo_metrics_compatible("minimum workable thickness", MINIMUM_WORKABLE_SEAM_THICKNESS)


def test_compare_preserves_provenance_and_no_false_absence(db_session):
    a = _doc(db_session, "DocA_Sheetaldhara.pdf")
    b = _doc(db_session, "DocB_empty_geo.pdf")
    _fact(
        db_session,
        a,
        metric_kind=MINIMUM_WORKABLE_SEAM_THICKNESS,
        thickness="0.90",
        thickness_unit="m",
        source_page=28,
        evidence_text="Minimum workable thickness = 0.90 m",
    )
    # B has formations only — no thickness
    _fact(
        db_session,
        b,
        metric_kind="formation",
        geological_formation="Barakar Formation",
        source_page=5,
        evidence_text="Barakar Formation is present",
    )
    db_session.commit()

    result = compare_documents(db_session, a.id, b.id, metrics=["minimum_workable_thickness"])
    assert not result.get("error")
    item = next(c for c in result["comparisons"] if c["metric"] == "minimum_workable_thickness")
    assert item["document_a"]["count"] >= 1
    evidence = item["document_a"]["items"][0]
    assert evidence["page"] == 28
    assert evidence["document_id"] == a.id
    assert evidence["metric_kind"] == MINIMUM_WORKABLE_SEAM_THICKNESS
    assert item["document_b"]["message"] == NO_COMPATIBLE_STRUCTURED
    # Must not claim proven absence
    assert "no such information" not in (item["document_b"].get("message") or "").lower()


def test_compare_recovers_workable_thickness_from_evidence_when_column_empty(db_session):
    """Older extracts left thickness=NULL but evidence has the value — compare must surface it."""
    a = _doc(db_session, "North_Parbelia_G3.pdf")
    b = _doc(db_session, "North_of_Labji_Pusla_Block.pdf")
    _fact(
        db_session,
        a,
        metric_kind=None,  # kind inferred from evidence
        thickness=None,
        original_value=None,
        source_page=28,
        evidence_text=(
            "minimum workable thickness has been considered for resource estimation "
            "is 0.90m for the seam as the resources are amenable to underground mining."
        ),
        status=FactStatus.REVIEW_REQUIRED.value,
    )
    _fact(
        db_session,
        b,
        metric_kind="formation",
        geological_formation="Barakar Formation",
        source_page=10,
        evidence_text="Barakar Formation identified",
    )
    db_session.commit()

    result = compare_documents(db_session, a.id, b.id, metrics=["minimum_workable_thickness"])
    item = next(c for c in result["comparisons"] if c["metric"] == "minimum_workable_thickness")
    assert item["document_a"]["count"] >= 1
    ev = item["document_a"]["items"][0]
    assert ev["value"] == "0.90"
    assert (ev.get("unit") or "m").lower().startswith("m")
    assert ev["page"] == 28
    assert ev["requires_human_verification"] is True
    assert item["document_b"]["message"] == NO_COMPATIBLE_STRUCTURED


def test_compare_resources_and_formations_recognized(db_session):
    a = _doc(db_session, "geo_a.pdf")
    b = _doc(db_session, "geo_b.pdf")
    _fact(
        db_session,
        a,
        metric_kind=RESOURCE_QUANTITY,
        seam_name="R4",
        original_value="1.67",
        original_unit="MT",
        source_page=31,
        evidence_text="Seam R4 resource = 1.67 MT",
    )
    _fact(
        db_session,
        b,
        metric_kind="resource",
        seam_name="R4",
        original_value="2.10",
        original_unit="MT",
        source_page=12,
        evidence_text="Seam R4 resource = 2.10 MT",
    )
    _fact(db_session, a, metric_kind="formation", geological_formation="Barakar Formation", source_page=3)
    _fact(db_session, b, metric_kind="formations", geological_formation="Barakar Formation", source_page=4)
    _fact(db_session, a, metric_kind="borehole", borehole_id="BH-12", source_page=8)
    _fact(db_session, b, metric_kind="boreholes", borehole_id="BH-99", source_page=9)
    db_session.commit()

    result = compare_documents(db_session, a.id, b.id)
    by_metric = {c["metric"]: c for c in result["comparisons"]}
    assert by_metric["resources"]["document_a"]["count"] >= 1
    assert by_metric["resources"]["document_b"]["count"] >= 1
    assert by_metric["formations"]["document_a"]["count"] >= 1
    assert by_metric["boreholes"]["document_a"]["count"] >= 1
