"""G1 — Geological document classification + fact extraction tests."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.geology.classifier import classify_document_text
from app.geology.extractor import extract_facts_from_page
from app.geology.taxonomy import DocumentDomain
from app.geology.units import to_metres
from app.models import Document, DocumentPage, GeologicalFact


GEO_PAGE = """
Geological exploration log — Borehole BH-27
Seam III intersected at depth 142.6 m with seam thickness 3.42 m.
Lithology: Coal underlain by sandstone.
Barakar Formation noted. Local fault observed near the section.
Ash content: 18.5 %
"""

PRODUCTION_PAGE = """
Coal Production Summary — March FY25
CIL production during the month was 85.81 MT against target 88.58 MT.
Subsidiary offtake and dispatch figures are tabulated below.
Achievement percentage is reported for each mine.
"""


def _make_pdf(path: Path, text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    doc.save(path)
    doc.close()
    return path


def test_classify_geological_document():
    result = classify_document_text(GEO_PAGE, filename_hint="notes.pdf")
    assert result.domain == DocumentDomain.GEOLOGICAL_EXPLORATION.value
    assert result.confidence >= 0.5
    assert "borehole" in (result.matched_terms.get(result.domain) or []) or "lithology" in str(
        result.matched_terms
    ).lower()


def test_classify_non_geological_production():
    result = classify_document_text(PRODUCTION_PAGE, filename_hint="srn-march-2025.pdf")
    assert result.domain == DocumentDomain.MINING_PRODUCTION.value
    assert result.domain != DocumentDomain.GEOLOGICAL_EXPLORATION.value


def test_classify_does_not_use_filename_alone_for_geology():
    # Filename suggests geology but body is empty / irrelevant → OTHER or weak
    result = classify_document_text("Monthly attendance sheet.", filename_hint="geological_report_2025.pdf")
    assert result.domain != DocumentDomain.GEOLOGICAL_EXPLORATION.value or result.confidence < 0.6


def test_extract_borehole_seam_depth_thickness_lithology():
    facts = extract_facts_from_page(GEO_PAGE, page_number=87, source_location="page:87")
    assert facts, "expected at least one geological fact"
    # Find a rich fact with borehole
    bh = next((f for f in facts if f.borehole_id), None)
    assert bh is not None
    assert bh.borehole_id == "BH-27"
    assert bh.source_page == 87
    assert bh.evidence_text
    assert "BH-27" in bh.evidence_text or "borehole" in bh.evidence_text.lower()

    # Seam / depth / thickness / lithology should appear on some draft(s)
    all_seams = [f.seam_name for f in facts if f.seam_name]
    all_depths = [f for f in facts if f.depth]
    all_thick = [f for f in facts if f.thickness]
    all_lith = [f for f in facts if f.lithology]
    assert any(s and "III" in s for s in all_seams)
    assert all_depths and all_depths[0].depth == "142.6"
    assert all_depths[0].depth_unit == "m"
    assert all_thick and all_thick[0].thickness == "3.42"
    assert all_thick[0].thickness_unit == "m"
    assert all_lith and any(x.lithology == "Coal" for x in all_lith)


def test_unit_preservation_and_normalization():
    facts = extract_facts_from_page(
        "Borehole BH-1 Depth: 10 ft Thickness: 120 cm Lithology: Shale",
        page_number=1,
    )
    assert facts
    d = next(f for f in facts if f.depth)
    assert d.depth == "10"
    assert d.depth_unit == "ft"
    assert d.depth_normalized_m == pytest.approx(to_metres(10.0, "ft") or 0.0)
    t = next(f for f in facts if f.thickness)
    assert t.thickness == "120"
    assert t.thickness_unit == "cm"
    assert t.thickness_normalized_m == pytest.approx(1.2)


def test_missing_values_not_invented():
    facts = extract_facts_from_page("Borehole BH-9 was drilled in Block A.", page_number=2)
    assert facts
    f = next(x for x in facts if x.borehole_id == "BH-9")
    assert f.depth is None
    assert f.thickness is None
    assert f.seam_name is None
    assert f.coal_quality_value is None


def test_no_hallucinated_values_on_empty_or_unrelated():
    assert extract_facts_from_page("", page_number=1) == []
    facts = extract_facts_from_page(PRODUCTION_PAGE, page_number=1)
    # Production text should not invent boreholes / seam depths
    assert not any(f.borehole_id for f in facts)
    assert not any(f.depth for f in facts)


def test_low_confidence_marked_for_review():
    # Minimal anchor without supporting measures → lower confidence / review
    facts = extract_facts_from_page("Seam X present.", page_number=3)
    assert facts
    assert all(f.status in {"review_required", "high_confidence", "extracted"} for f in facts)
    # Thin evidence should not silently be high_confidence without more fields
    thin = facts[0]
    if thin.extraction_confidence < 0.85:
        assert thin.status == "review_required"


def test_formation_and_structure_and_quality():
    facts = extract_facts_from_page(GEO_PAGE, page_number=87)
    assert any(f.geological_formation and "Barakar" in f.geological_formation for f in facts)
    assert any(f.geological_structure == "fault" for f in facts)
    assert any(f.coal_quality_parameter == "Ash" and f.coal_quality_value == "18.5" for f in facts)


def test_malformed_extraction_ignored():
    facts = extract_facts_from_page("Depth: not-a-number m Thickness: ?? m", page_number=1)
    # Regex requires numeric tokens — should not create depth/thickness facts
    assert not any(f.depth for f in facts)
    assert not any(f.thickness for f in facts)


def test_pipeline_persist_with_provenance(client, db_session, fixtures_dir):
    pdf = _make_pdf(fixtures_dir / "geo_log.pdf", GEO_PAGE)
    with pdf.open("rb") as f:
        up = client.post(
            "/api/documents/upload",
            files={"file": ("geo_log.pdf", f, "application/pdf")},
            data={"mine_name": "Block A", "document_category": "General"},
        )
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["page_count"] >= 1
    meta = body.get("meta") or {}
    assert "g1_classification" in meta
    assert meta["g1_classification"]["domain"] == DocumentDomain.GEOLOGICAL_EXPLORATION.value

    geo = body.get("geological_facts") or []
    assert len(geo) >= 1
    assert any(g.get("borehole_id") == "BH-27" for g in geo)
    sample = next(g for g in geo if g.get("borehole_id") == "BH-27")
    assert sample["source_document_id"] == body["id"]
    assert sample["source_page"] == 1
    assert sample["evidence_text"]

    # API list endpoint
    listed = client.get(f"/api/documents/{body['id']}/geological-facts")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    # DB row exists
    rows = db_session.query(GeologicalFact).filter(GeologicalFact.document_id == body["id"]).all()
    assert rows
    assert all(r.evidence_text for r in rows)


def test_production_pdf_not_forced_geological(client, fixtures_dir):
    pdf = _make_pdf(fixtures_dir / "prod.pdf", PRODUCTION_PAGE)
    with pdf.open("rb") as f:
        up = client.post(
            "/api/documents/upload",
            files={"file": ("prod.pdf", f, "application/pdf")},
            data={"document_category": "General"},
        )
    assert up.status_code == 200, up.text
    meta = up.json().get("meta") or {}
    assert meta.get("g1_classification", {}).get("domain") == DocumentDomain.MINING_PRODUCTION.value
    assert (up.json().get("geological_facts") or []) == []
