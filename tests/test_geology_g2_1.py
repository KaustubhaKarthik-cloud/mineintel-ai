"""G2.1 — Uncorrelated seams + workable vs named seam-thickness grounding.

Synthetic source text only. No hard-coded document answers.
"""

from __future__ import annotations

from app.assistant.evidence_filter import evidence_compatible
from app.assistant.geological_retriever import retrieve_geological_facts
from app.assistant.query_router import parse_query
from app.geology.extractor import extract_facts_from_page
from app.geology.metric_kinds import (
    MINIMUM_WORKABLE_SEAM_THICKNESS,
    classify_evidence_metric_kind,
    classify_query_thickness_metric,
    metrics_compatible,
)
from app.geology.seam_ids import is_valid_seam_identifier, seam_display_label
from app.models import Document, DocumentPage, FactStatus, GeologicalFact, IndexStatus


TWO_SEAM_PAGE = """
v) There are 2 seams found in block during present investigation. The R4 seam
of Raniganj Formation and an uncorrelated coal seam of Barakar Formation is
present in the block. The barakar seam is left uncorrelated because it is not
persistent and could not be correlated with the available data.
"""

WORKABLE_PAGE = """
5.2.1.3 MINIMUM THICKNESS
The minimum workable thickness has been considered for resource
estimation is 0.90m for the seam as the resources are amenable to underground
mining.
"""

GENERIC_CM_PAGE = """
carbonaceous shale high (combustible bands) below 100 cm thickness and
dirt bands are treated separately in the methodology section.
"""

R4_THICKNESS_PAGE = """
Borehole CMNPB-01 intersected Seam R4 with seam thickness 1.05 m.
Seam R4 thickness varies from 0.90 m to 1.20 m within the drilled section.
"""

FORMATION_THICK_PAGE = """
The average thickness of the Barakar Formation in the area is 150 m to 250 m.
"""


def _doc(db, name="synthetic_g21.pdf") -> Document:
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


def test_1_two_seam_entities_extracted():
    facts = extract_facts_from_page(TWO_SEAM_PAGE, page_number=11)
    named = [f for f in facts if f.seam_name and is_valid_seam_identifier(f.seam_name)]
    uncorr = [
        f
        for f in facts
        if (f.seam_status or "").lower() == "uncorrelated"
    ]
    assert any(f.seam_name and "R4" in f.seam_name for f in named)
    assert uncorr, "expected an uncorrelated seam entity"
    for f in uncorr:
        assert f.seam_name is None
        assert not is_valid_seam_identifier(f.seam_name or "")
        assert f.geological_formation and "Barakar" in f.geological_formation
        assert f.evidence_text and "uncorrelated" in f.evidence_text.lower()


def test_2_r4_thickness_rejects_workable_and_generic(db_session):
    doc = _doc(db_session)
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            domain="geological",
            metric_kind="minimum_workable_seam_thickness",
            thickness="0.90",
            thickness_unit="m",
            source_page=28,
            evidence_text="minimum workable thickness ... is 0.90m for the seam",
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.9,
        )
    )
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            domain="geological",
            metric_kind="seam_thickness",
            thickness="100",
            thickness_unit="cm",
            source_page=25,
            evidence_text="combustible bands below 100 cm thickness",
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.8,
        )
    )
    db_session.commit()
    plan = parse_query("What is the thickness of Seam R4?")
    assert plan.geological_seam and "R4" in plan.geological_seam
    assert plan.metric == "seam_thickness" or "seam_thickness" in plan.geological_metrics
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert hits == []


def test_2b_r4_thickness_accepts_associated_evidence(db_session):
    doc = _doc(db_session, "r4_thick.pdf")
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            domain="geological",
            metric_kind="seam_thickness",
            seam_name="Seam R4",
            seam_status="named",
            thickness_min="0.90",
            thickness_max="1.20",
            thickness_unit="m",
            source_page=55,
            evidence_text="Seam R4 thickness varies from 0.90 m to 1.20 m",
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.95,
        )
    )
    db_session.commit()
    plan = parse_query("What is the thickness of Seam R4?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert hits
    assert all(h.metric == "seam_thickness" for h in hits)
    assert all("0.90" in (h.value or "") or (h.value_min == "0.90") for h in hits)


def test_3_formation_thickness_guard():
    plan = parse_query("What is the thickness of the Barakar Formation?")
    assert classify_query_thickness_metric(plan.raw_question) == "formation_thickness"
    assert "formation_thickness" in (plan.geological_metrics or []) or plan.metric == "formation_thickness"
    kind = classify_evidence_metric_kind(
        text="Seam R4 thickness 1.05 m",
        seam_name="Seam R4",
        has_thickness=True,
        requested="formation_thickness",
    )
    assert not metrics_compatible("formation_thickness", kind)
    workable = classify_evidence_metric_kind(
        text="minimum workable thickness is 0.90m",
        has_thickness=True,
        requested="formation_thickness",
    )
    assert workable == MINIMUM_WORKABLE_SEAM_THICKNESS
    assert not metrics_compatible("formation_thickness", workable)


def test_4_unnamed_seam_identity_no_invented_id():
    facts = extract_facts_from_page(TWO_SEAM_PAGE, page_number=11)
    uncorr = [f for f in facts if (f.seam_status or "").lower() == "uncorrelated"]
    assert uncorr
    for f in uncorr:
        assert f.seam_name is None
        label = seam_display_label(seam_name=f.seam_name, seam_status=f.seam_status)
        assert label and "uncorrelated" in label.lower()
        assert "Barakar" not in (label or "")  # formation is separate, not inventing Seam Barakar


def test_5_multi_seam_distinction_in_listing(db_session):
    doc = _doc(db_session, "two_seams.pdf")
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            domain="geological",
            metric_kind="seam",
            seam_name="Seam R4",
            seam_status="named",
            geological_formation="Raniganj Formation",
            source_page=11,
            evidence_text="The R4 seam of Raniganj Formation",
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.9,
        )
    )
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            domain="geological",
            metric_kind="seam",
            seam_name=None,
            seam_status="uncorrelated",
            geological_formation="Barakar Formation",
            source_page=11,
            evidence_text="an uncorrelated coal seam of Barakar Formation",
            status=FactStatus.REVIEW_REQUIRED.value,
            extraction_confidence=0.6,
        )
    )
    db_session.commit()
    plan = parse_query("What coal seams are identified in this report?")
    hits = retrieve_geological_facts(
        db_session,
        plan,
        verified_only=False,
        include_unverified=True,
        document_ids=[doc.id],
    )
    assert len(hits) >= 2
    values = " | ".join((h.value or "") for h in hits)
    assert "R4" in values
    assert "uncorrelated" in values.lower() or "Uncorrelated" in values
    assert "Barakar" in values
    # No invented Barakar seam identifier
    assert not any(
        h.seam_name and "Barakar" in (h.seam_name or "") for h in hits
    )


def test_6_mining_regression_routing():
    for q in (
        "What was CIL production in March FY25?",
        "How much coal did ECL produce in FY25?",
        "What was BCCL production?",
        "CCL coal production FY25",
        "Captive/Others production in March FY25",
    ):
        plan = parse_query(q)
        assert plan.is_geological is False, q


def test_workable_metric_routed_separately():
    plan = parse_query("What is the minimum workable thickness considered in the report?")
    assert plan.is_geological
    assert (
        plan.metric == "minimum_workable_seam_thickness"
        or "minimum_workable_seam_thickness" in (plan.geological_metrics or [])
    )


def test_workable_extracted_not_as_seam_thickness():
    facts = extract_facts_from_page(WORKABLE_PAGE, page_number=28)
    workable = [f for f in facts if f.metric_kind == "minimum_workable_seam_thickness"]
    assert workable
    assert all(f.seam_name is None for f in workable)
    assert any(f.thickness == "0.90" or f.thickness == "0.9" for f in workable)


def test_evidence_filter_rejects_workable_for_r4_thickness():
    plan = parse_query("What is the thickness of Seam R4?")
    bad = evidence_compatible(
        plan,
        WORKABLE_PAGE,
        require_entity=False,
        require_metric=True,
    )
    assert not bad.ok
    good = evidence_compatible(
        plan,
        R4_THICKNESS_PAGE,
        require_entity=False,
        require_metric=True,
    )
    assert good.ok, good.reasons


def test_r4_thickness_extracted_from_associated_text():
    facts = extract_facts_from_page(R4_THICKNESS_PAGE, page_number=55)
    thick = [
        f
        for f in facts
        if f.seam_name
        and "R4" in f.seam_name
        and (f.thickness or f.thickness_min)
    ]
    assert thick
    assert all(f.metric_kind in {None, "seam_thickness"} or f.seam_name for f in thick)
