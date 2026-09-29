"""Document-grounded geological map coordinates — never invent locations."""

from __future__ import annotations

from app.geology.coordinates import (
    LOCATION_UNAVAILABLE,
    list_document_locations,
    parse_coordinates_from_meta,
    parse_coordinates_from_text,
)
from app.models import Document, FactStatus, GeologicalFact, IndexStatus


def test_parse_valid_lat_lon_pair():
    assert parse_coordinates_from_text("Latitude: 23.45 N, Longitude: 84.12 E") == (
        23.45,
        84.12,
    )


def test_parse_southern_western_hemispheres():
    lat, lon = parse_coordinates_from_text("lat=12.5 S, lon=45.0 W")
    assert abs(lat - (-12.5)) < 1e-6
    assert abs(lon - (-45.0)) < 1e-6


def test_parse_rejects_out_of_range():
    assert parse_coordinates_from_text("lat=99.0, lon=10.0") is None
    assert parse_coordinates_from_text("lat=10.0, lon=200.0") is None


def test_parse_rejects_bare_number_pairs_from_ocr():
    """OCR tables like '2 CSNLP-02,04' must never become coordinates."""
    junk = (
        "ECTION --------------------- 1) FULL SEAM INTERSECTION: 2 CSNLP-02,04 "
        "II] DEPTH RANGE (FLOOR) (M) --"
    )
    assert parse_coordinates_from_text(junk) is None
    assert parse_coordinates_from_text("intersection: 2,04") is None
    assert parse_coordinates_from_text("values 23.5, 84.1") is None  # no labels/hemispheres


def test_parse_meta_coordinates():
    assert parse_coordinates_from_meta({"latitude": 22.1, "longitude": 83.2}) == (22.1, 83.2)
    assert parse_coordinates_from_meta({"lat": "bad", "lon": 1}) is None
    assert parse_coordinates_from_meta(None) is None


def test_list_locations_unavailable_without_coords(db_session):
    doc = Document(
        filename="no_coords.pdf",
        original_filename="no_coords.pdf",
        file_path="/tmp/no_coords.pdf",
        file_type="pdf",
        status="extracted",
        index_status=IndexStatus.INDEXED.value,
        document_category="Geological Exploration Report",
        version=1,
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            domain="geological",
            geological_formation="Barakar Formation",
            evidence_text="Barakar Formation present in the block.",
            source_page=3,
            status=FactStatus.HIGH_CONFIDENCE.value,
            extraction_confidence=0.9,
        )
    )
    db_session.commit()

    result = list_document_locations(db_session, document_id=doc.id)
    assert result["available"] is False
    assert result["message"] == LOCATION_UNAVAILABLE
    assert result["items"] == []


def test_list_locations_from_explicit_evidence(db_session):
    doc = Document(
        filename="with_coords.pdf",
        original_filename="with_coords.pdf",
        file_path="/tmp/with_coords.pdf",
        file_type="pdf",
        status="extracted",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            domain="geological",
            evidence_text="Block centre Latitude: 23.8124 N, Longitude: 86.4310 E surveyed.",
            source_page=5,
            status=FactStatus.HIGH_CONFIDENCE.value,
            extraction_confidence=0.95,
        )
    )
    db_session.commit()

    result = list_document_locations(db_session, document_id=doc.id)
    assert result["available"] is True
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert abs(item["latitude"] - 23.8124) < 1e-4
    assert abs(item["longitude"] - 86.4310) < 1e-4
    assert item["page"] == 5
    assert item["document_id"] == doc.id
    assert "korea" not in (item.get("document_name") or "").lower()


def test_no_default_or_unrelated_location(db_session):
    """Empty DB / no coords must never invent a marker."""
    result = list_document_locations(db_session)
    # May be empty or only previously seeded coords — never invent Korea/defaults
    for item in result.get("items") or []:
        assert item.get("latitude") is not None
        assert item.get("longitude") is not None
        assert abs(float(item["latitude"])) <= 90
        # Must not be a mysterious Seoul-ish default planted by us
        assert not (
            abs(float(item["latitude"]) - 37.5665) < 0.01
            and abs(float(item["longitude"]) - 126.978) < 0.01
        )
