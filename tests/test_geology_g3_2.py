"""G3.2 — real-document formation fragment rejection + resource routing."""

from __future__ import annotations

from app.assistant.geological_retriever import retrieve_geological_facts
from app.assistant.query_router import parse_query
from app.geology.entities import (
    extract_formations_from_text,
    is_plausible_formation_name,
    normalize_formation_name,
)
from app.geology.extractor import extract_facts_from_page
from app.models import Document, FactStatus, GeologicalFact, IndexStatus


def _doc(db, name="g32.pdf") -> Document:
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


def test_valid_formation_name_survives():
    assert is_plausible_formation_name("Raniganj Formation")
    assert normalize_formation_name("barakar formation") == "Barakar Formation"
    assert "Raniganj Formation" in extract_formations_from_text(
        "The Raniganj Formation hosts coal seams."
    )


def test_reject_through_the_formation():
    assert not is_plausible_formation_name("through the Formation")
    assert extract_formations_from_text("passed through the Formation boundary") == []


def test_reject_lithology_of_formation():
    assert not is_plausible_formation_name("lithology of Formation")
    assert extract_formations_from_text("lithology of Formation is described") == []


def test_reject_guide_to_formation_characteristics():
    text = "qualitative guide to formation characteristics of the sediments"
    assert extract_formations_from_text(text) == []
    assert not is_plausible_formation_name("guide to Formation", context=text)


def test_reject_coaly_formation():
    assert not is_plausible_formation_name("coaly Formation")
    assert extract_formations_from_text("coaly Formation observed in cores") == []


def test_reject_separate_carbonaceous_formation():
    assert not is_plausible_formation_name("separate carbonaceous Formation")
    assert (
        extract_formations_from_text(
            "separate carbonaceous Formation packages are present"
        )
        == []
    )


def test_listing_excludes_invalid_fragments(db_session):
    doc = _doc(db_session)
    for name, page in (
        ("Raniganj Formation", 11),
        ("Barakar Formation", 33),
        ("through the Formation", 18),
        ("lithology of Formation", 19),
        ("guide to Formation", 21),
        ("coaly Formation", 22),
        ("separate carbonaceous Formation", 23),
        ("of Raniganj Formation", 14),
    ):
        db_session.add(
            GeologicalFact(
                document_id=doc.id,
                metric_kind="formation",
                geological_formation=name,
                source_page=page,
                evidence_text=f"{name} text",
                status=FactStatus.REVIEW_REQUIRED.value,
                extraction_confidence=0.7,
            )
        )
    db_session.commit()
    plan = parse_query("What formations are present in this report?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=False, include_unverified=True, document_ids=[doc.id]
    )
    vals = [h.value for h in hits]
    assert set(vals) == {"Raniganj Formation", "Barakar Formation"}
    blob = " ".join(vals).lower()
    for bad in ("through", "lithology", "guide", "coaly", "carbonaceous", "of raniganj"):
        assert bad not in blob


def test_formation_dedupe_keeps_one(db_session):
    doc = _doc(db_session, "g32b.pdf")
    for page in (11, 27, 33):
        db_session.add(
            GeologicalFact(
                document_id=doc.id,
                metric_kind="formation",
                geological_formation="Raniganj Formation",
                source_page=page,
                evidence_text="Raniganj Formation",
                status=FactStatus.APPROVED.value,
                extraction_confidence=0.9,
            )
        )
    db_session.commit()
    plan = parse_query("What formations are present in this report?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert [h.value for h in hits] == ["Raniganj Formation"]


def test_resource_intent_not_seam():
    plan = parse_query("What is the inferred resource for Seam R4?")
    assert plan.geological_intent == "resource"
    assert plan.metrics[0] == "resource"
    assert plan.geological_seam == "Seam R4"
    assert plan.listing_intent is False


def test_resource_structured_retrieval(db_session):
    doc = _doc(db_session, "g32res.pdf")
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            metric_kind="resource",
            seam_name="Seam R4",
            seam_status="named",
            original_value="1.67",
            original_unit="MT",
            source_page=31,
            evidence_text=(
                "Total Inferred Resource of 1.67 MT for coal have been estimated "
                "for seam R4. The resource has been placed under Inferred category."
            ),
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.9,
        )
    )
    # Decoy seam listing fact without resource quantity
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            metric_kind="seam",
            seam_name="Seam R4",
            seam_status="named",
            source_page=11,
            evidence_text="Seam R4 of Raniganj Formation is present",
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.9,
        )
    )
    db_session.commit()
    plan = parse_query("What is the inferred resource for Seam R4?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert hits
    assert hits[0].metric == "resource"
    assert hits[0].value == "1.67"
    assert (hits[0].unit or "").upper().startswith("MT")
    assert hits[0].seam_name == "Seam R4"
    assert hits[0].page == 31


def test_resource_extractor_generic():
    text = (
        "Total Inferred Resource of 2.45 MT for coal have been estimated for Seam III. "
        "The resource has been placed under Inferred category."
    )
    drafts = extract_facts_from_page(text, page_number=10)
    res = [d for d in drafts if (d.metric_kind or "") == "resource"]
    assert res
    assert res[0].original_value == "2.45"
    assert res[0].seam_name and "III" in res[0].seam_name


def test_seam_listing_still_seam_intent():
    plan = parse_query("What coal seams are identified in this report?")
    assert plan.geological_intent in {"seam", "seam_listing"}
    assert plan.metrics[0] == "seam"


def test_resource_not_listing_intent():
    plan = parse_query("What is the inferred resource for Seam R4?")
    assert plan.listing_intent is False
