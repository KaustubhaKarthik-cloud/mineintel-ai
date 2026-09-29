"""Geological Explorer facts table — display column mapping (presentation only)."""

from __future__ import annotations

from app.geology.explorer import fact_to_explorer_item
from app.models import Document, FactStatus, GeologicalFact, IndexStatus


def _doc(db, name: str = "North_Parbelia_G3.pdf") -> Document:
    d = Document(
        filename=name,
        original_filename=name,
        file_path=f"/tmp/{name}",
        file_type="pdf",
        status="extracted",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db.add(d)
    db.flush()
    return d


def test_structured_entity_metric_value_displayed(db_session):
    doc = _doc(db_session)
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        metric_kind="minimum_workable_seam_thickness",
        seam_name="R4",
        thickness="0.90",
        thickness_unit="m",
        source_page=28,
        evidence_text="minimum workable thickness is 0.90m",
        status=FactStatus.HIGH_CONFIDENCE.value,
        extraction_confidence=0.9,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert "Parbelia" in str(item["display_entity"])
    assert "workable" in str(item["display_metric"]).lower()
    assert "0.90" in str(item["display_value"])
    assert item.get("display_from_evidence") is not True


def test_coal_lithology_not_shown_as_value_when_not_lithology_metric(db_session):
    """Bare lithology='Coal' must not become Value when metric_kind is unset."""
    doc = _doc(db_session)
    before = db_session.query(GeologicalFact).count()
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        metric_kind=None,
        lithology="Coal",
        seam_name=None,
        geological_formation=None,
        borehole_id=None,
        thickness=None,
        original_value=None,
        source_page=6,
        evidence_text="Coal resources of the block are under assessment.",
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.4,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item["display_value"] != "Coal"
    assert item["display_value"] == "Not available"
    assert "resource" in str(item["display_metric"]).lower()
    assert item["status"] == FactStatus.REVIEW_REQUIRED.value
    assert db_session.query(GeologicalFact).count() == before + 1


def test_coal_resource_quantity_from_evidence(db_session):
    doc = _doc(db_session)
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        lithology="Coal",
        source_page=31,
        evidence_text="Coal Resource: 1.67 MT",
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.5,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item["display_metric"] == "Coal Resource"
    assert "1.67" in str(item["display_value"])
    assert "MT" in str(item["display_value"]).upper()
    assert item["display_value"] != "Coal"


def test_minimum_workable_thickness_from_evidence(db_session):
    doc = _doc(db_session)
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        source_page=28,
        evidence_text="Minimum workable seam thickness: 0.90 m",
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.5,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert "workable" in str(item["display_metric"]).lower()
    assert "thickness" in str(item["display_metric"]).lower()
    assert "0.90" in str(item["display_value"])


def test_barakar_formation_metric_value(db_session):
    doc = _doc(db_session)
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        metric_kind="formation",
        geological_formation="Barakar Formation",
        source_page=28,
        evidence_text="Barakar Formation",
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.6,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item["display_metric"] == "Formation"
    assert "Barakar" in str(item["display_value"])
    assert "Parbelia" in str(item["display_entity"])
    assert item["display_value"] != "Coal"


def test_borehole_js2_metric_value(db_session):
    doc = _doc(db_session, "North_of_Labji_Pusla_Block.pdf")
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        metric_kind="borehole",
        borehole_id="JS-2",
        source_page=19,
        evidence_text="Borehole JS-2",
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.6,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item["display_metric"] == "Borehole"
    assert item["display_value"] == "JS-2"
    assert "Labji" in str(item["display_entity"])


def test_structured_values_take_priority_over_evidence(db_session):
    doc = _doc(db_session)
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        metric_kind="minimum_workable_seam_thickness",
        thickness="0.90",
        thickness_unit="m",
        source_page=28,
        evidence_text="Coal Resource: 99.99 MT and unrelated noise",
        status=FactStatus.HIGH_CONFIDENCE.value,
        extraction_confidence=0.9,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert "0.90" in str(item["display_value"])
    assert "99.99" not in str(item["display_value"])
    assert "workable" in str(item["display_metric"]).lower()


def test_missing_quantity_not_available(db_session):
    doc = _doc(db_session)
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        lithology="Coal",
        source_page=4,
        evidence_text="Coal",
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.3,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item["display_value"] == "Not available"
    assert item["display_value"] != "Coal"


def test_evidence_fallback_coordinates_still_work(db_session):
    doc = _doc(db_session, "evidence_only.pdf")
    evidence = (
        "Location & Accessibility\n"
        "Cardinal Point Coordinates\n"
        "Latitude: 23.45 N\n"
        "Longitude: 84.12 E\n"
        "The block is approachable by road."
    )
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        source_page=4,
        evidence_text=evidence,
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.4,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item["display_entity"]
    assert item["display_entity"] != "—"
    assert "coordinate" in str(item["display_metric"]).lower() or "latitude" in str(
        item["display_value"]
    ).lower()
    assert "latitude" in str(item["display_value"]).lower() or "23.45" in str(item["display_value"])
    assert item["display_from_evidence"] is True
    assert item.get("coordinate_evidence_only") is True
    assert item["requires_human_verification"] is True


def test_no_structured_no_evidence_not_available(db_session):
    doc = _doc(db_session, "empty.pdf")
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        source_page=1,
        evidence_text=None,
        status=FactStatus.EXTRACTED.value,
        extraction_confidence=0.1,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item["display_value"] == "Not available"
    assert item["display_metric"] == "Not available"
    assert not item.get("display_from_evidence")


def test_coordinate_looking_evidence_not_promoted_to_map(db_session):
    doc = _doc(db_session, "coords_review.pdf")
    evidence = (
        "Location & Accessibility. Cardinal Point Coordinates. "
        "Latitude: 23.45 N, Longitude: 84.12 E"
    )
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        source_page=4,
        evidence_text=evidence,
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.5,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item.get("coordinate_evidence_only") is True
    assert "map_verified" not in item or item.get("map_verified") is not True
    assert item["requires_human_verification"] is True


def test_review_required_remains_visible(db_session):
    doc = _doc(db_session, "review.pdf")
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        evidence_text="Some geological note without structured fields.",
        source_page=7,
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.3,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item["status"] == FactStatus.REVIEW_REQUIRED.value
    assert item["review_bucket"] == "review_required"
    assert item["requires_human_verification"] is True
    assert item["display_value"] != "—"
    assert item["evidence_preview"] or item["evidence_text"]


def test_partial_structured_preserves_fields(db_session):
    doc = _doc(db_session, "partial.pdf")
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        metric_kind="formation",
        geological_formation="Barakar Formation",
        original_value=None,
        thickness=None,
        source_page=10,
        evidence_text="Barakar Formation is well developed in the western part of the block.",
        status=FactStatus.REVIEW_REQUIRED.value,
        extraction_confidence=0.6,
    )
    db_session.add(row)
    db_session.commit()

    item = fact_to_explorer_item(row, doc)
    assert item["formation_name"] == "Barakar Formation" or "Barakar" in str(item["display_value"])
    assert item["display_metric"] == "Formation"
    assert "Barakar" in str(item["display_value"])
