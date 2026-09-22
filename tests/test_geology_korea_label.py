"""Korea district presentation — Indian district, not a country."""

from __future__ import annotations

from app.geology.location_labels import annotate_evidence_display, format_location_display


def test_korea_chhattisgarh_district_label():
    text = "DISTRICT : KOREA, CHHATTISGARH\nBlock: North of Labji-Pusla"
    assert format_location_display(text) == "Korea District, Chhattisgarh, India"
    annotated = annotate_evidence_display(text)
    assert annotated is not None
    assert annotated.startswith("[Korea District, Chhattisgarh, India]")
    assert "DISTRICT : KOREA, CHHATTISGARH" in annotated
    assert "South Korea" not in annotated
    assert "Republic of Korea" not in annotated


def test_unrelated_text_unchanged():
    text = "Seam R4 thickness 1.2 m in Raniganj Formation."
    assert format_location_display(text) is None
    assert annotate_evidence_display(text) == text
