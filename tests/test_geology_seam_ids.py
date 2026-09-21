"""G1 seam-identifier quality — context-aware extraction (no document hard-codes)."""

from __future__ import annotations

from app.assistant.geological_retriever import plausible_seam_name
from app.geology.extractor import extract_facts_from_page
from app.geology.seam_ids import is_valid_seam_identifier, normalize_seam_identifier


def test_a_coal_seam_not_identifier():
    assert not is_valid_seam_identifier("coal seam")
    assert normalize_seam_identifier("coal seam") is None
    assert not plausible_seam_name("coal seam")


def test_b_seam_found_not_identifier():
    assert not is_valid_seam_identifier("seam found")
    assert not plausible_seam_name("Seam found")


def test_c_seam_wise_not_identifier():
    assert not is_valid_seam_identifier("seam wise")
    assert not plausible_seam_name("Seam wise")


def test_d_geophysical_coal_seam_not_identifier():
    assert not is_valid_seam_identifier("geophysical log ... coal seam")
    assert not plausible_seam_name("Seam GEOPHYSICAL")
    facts = extract_facts_from_page(
        "The interpretation uses the geophysical log against coal seam GEOPHYSICAL section.",
        page_number=1,
    )
    assert not any(f.seam_name for f in facts)


def test_e_seam_r4():
    assert normalize_seam_identifier("Seam R4") == "Seam R4"
    assert plausible_seam_name("Seam R4")


def test_f_r4_seam():
    assert normalize_seam_identifier("R4 seam") == "Seam R4"
    facts = extract_facts_from_page("R4 seam thickness is 1.20 m in the block.", page_number=2)
    assert any(f.seam_name == "Seam R4" for f in facts)


def test_g_seam_iii_top():
    assert normalize_seam_identifier("Seam III Top") == "Seam III Top"
    facts = extract_facts_from_page(
        "Seam III Top varies from 0.69 m to 1.65 m within the block.",
        page_number=3,
    )
    assert any(f.seam_name == "Seam III Top" for f in facts)


def test_h_seam_iii_bottom():
    assert normalize_seam_identifier("Seam III Bottom") == "Seam III Bottom"
    facts = extract_facts_from_page(
        "Seam III Bottom general thickness 0.55 m to 0.85 m.",
        page_number=4,
    )
    assert any(f.seam_name == "Seam III Bottom" for f in facts)


def test_i_formation_association_preserved():
    text = (
        "Seam R4 occurs within the Raniganj Formation. "
        "An uncorrelated coal seam is noted in the Barakar Formation."
    )
    facts = extract_facts_from_page(text, page_number=5)
    r4 = next((f for f in facts if f.seam_name == "Seam R4"), None)
    assert r4 is not None
    # Formation may be attached on the same or a nearby fact; never invent Seam Barakar
    assert not any((f.seam_name or "").lower() == "seam barakar" for f in facts)
    formations = [f.geological_formation for f in facts if f.geological_formation]
    assert any(f and "Formation" in f for f in formations)


def test_j_listing_rejects_generic_phrases():
    """Structured listing path must not treat narrative leftovers as seam IDs."""
    bad = [
        "Seam GEOPHYSICAL",
        "Seam dirt",
        "Seam only",
        "Seam found",
        "Seam wise",
        "Seam Barakar",
        "Seam is",
        "Seam of",
    ]
    for name in bad:
        assert not plausible_seam_name(name), name
    good = ["Seam R4", "Seam IV", "Seam III Top", "Seam III Bottom", "Seam VIA", "Seam II"]
    for name in good:
        assert plausible_seam_name(name), name


def test_reject_dirt_only_wise_in_page_extraction():
    text = (
        "Seam dirt band. Seam only. Seam found during investigation. "
        "Seam wise correlation. Seam R4 is workable."
    )
    facts = extract_facts_from_page(text, page_number=6)
    seams = {f.seam_name for f in facts if f.seam_name}
    assert seams == {"Seam R4"} or seams <= {"Seam R4"}
    assert "Seam dirt" not in seams
    assert "Seam only" not in seams
    assert "Seam found" not in seams
    assert "Seam wise" not in seams
