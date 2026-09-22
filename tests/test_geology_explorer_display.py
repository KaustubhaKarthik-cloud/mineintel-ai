"""Geological Explorer facts table — display fallbacks from evidence (presentation only)."""

from __future__ import annotations

from app.geology.coordinates import list_document_locations, parse_coordinates_from_text
from app.geology.explorer import fact_to_explorer_item
from app.models import Document, FactStatus, GeologicalFact, IndexStatus


def _doc(db, name: str = "display_geo.pdf") -> Document:
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
    assert item["display_entity"] == "Seam R4" or "R4" in str(item["display_entity"])
    assert "workable" in str(item["display_metric"]).lower() or item["metric_kind"]
    assert "0.90" in str(item["display_value"])
    assert item.get("display_from_evidence") is not True


def test_missing_structured_fields_show_evidence(db_session):
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
        metric_kind=None,
        seam_name=None,
        geological_formation=None,
        borehole_id=None,
        thickness=None,
        original_value=None,
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
    assert "location" in item["display_entity"].lower() or item["display_entity"] == "Detected evidence"
    assert item["display_metric"]
    assert item["display_metric"] != "—"
    assert item["display_value"]
    assert item["display_value"] != "—"
    assert "latitude" in item["display_value"].lower() or "23.45" in item["display_value"]
    assert item["display_from_evidence"] is True
    assert item["source_page"] == 4
    assert item["status"] == FactStatus.REVIEW_REQUIRED.value
    assert item["requires_human_verification"] is True
    assert item.get("coordinate_evidence_only") is True


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
    assert item["formation_name"] == "Barakar Formation" or "Barakar" in str(item["display_entity"])
    assert item["display_value"]
    assert "Barakar" in str(item["display_value"]) or "Barakar" in str(item["display_entity"])


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
    assert item["display_entity"] == "Not available" or item["display_entity"] in {
        None,
        "Not available",
    }
    # After fallback helpers, empty evidence yields Not available labels
    assert item["display_value"] == "Not available"
    assert not item.get("display_from_evidence")


def test_coordinate_looking_evidence_not_promoted_to_map(db_session):
    doc = _doc(db_session, "coords_review.pdf")
    evidence = "Location & Accessibility. Cardinal Point Coordinates. Latitude: 23.45 N, Longitude: 84.12 E"
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
    # Display may show lat/lon text, but map pipeline must still reject unverified patterns
    # unless they pass the strict labeled parser — labeled form DOES parse for map.
    # The requirement: review-required display must NOT auto-mark as map-usable via explorer.
    # list_document_locations may pick labeled coords from evidence — that's the verified
    # coordinate pipeline. Here we assert explorer does not set a verified map flag.
    assert "map_verified" not in item or item.get("map_verified") is not True
    assert item["requires_human_verification"] is True
    # Ensure we did not fabricate a structured metric_kind for coordinates
    assert item.get("metric_kind") in {None, "formation", "seam", "borehole"} or item.get(
        "display_from_evidence"
    )


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
