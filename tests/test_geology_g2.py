"""G2 — Geological structured storage + query understanding tests.

No hard-coded document answers. Synthetic facts only; live docs used only as
optional integration fixtures when present on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.assistant.geological_retriever import retrieve_geological_facts
from app.assistant.query_router import parse_query
from app.assistant.service import ask_assistant
from app.geology.entities import (
    boreholes_match,
    formations_match,
    seams_match,
)
from app.geology.review import review_geological_fact
from app.geology.service import extract_and_persist_geological_facts, geological_fact_to_dict
from app.models import Document, DocumentPage, FactStatus, GeologicalFact, IndexStatus


def _doc(db, name: str = "synthetic_geo.pdf") -> Document:
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


def _page(db, doc: Document, n: int, text: str) -> DocumentPage:
    p = DocumentPage(
        document_id=doc.id,
        page_number=n,
        text=text,
        source_type="pdf_page",
        source_location=f"page:{n}",
    )
    db.add(p)
    db.flush()
    return p


def _fact(
    db,
    doc: Document,
    *,
    page: int = 1,
    seam: str | None = None,
    borehole: str | None = None,
    formation: str | None = None,
    lithology: str | None = None,
    thickness: str | None = None,
    thickness_min: str | None = None,
    thickness_max: str | None = None,
    depth: str | None = None,
    metric_kind: str | None = None,
    status: str = FactStatus.HIGH_CONFIDENCE.value,
    evidence: str = "synthetic evidence",
) -> GeologicalFact:
    row = GeologicalFact(
        document_id=doc.id,
        domain="geological",
        metric_kind=metric_kind,
        seam_name=seam,
        borehole_id=borehole,
        geological_formation=formation,
        lithology=lithology,
        thickness=thickness,
        thickness_min=thickness_min,
        thickness_max=thickness_max,
        thickness_unit="m" if (thickness or thickness_min) else None,
        depth=depth,
        depth_unit="m" if depth else None,
        original_value=thickness
        or (
            f"{thickness_min}–{thickness_max}"
            if thickness_min and thickness_max
            else depth or seam
        ),
        original_unit="m" if (thickness or thickness_min or depth) else None,
        value_qualifier="range" if thickness_min and thickness_max else None,
        source_page=page,
        evidence_text=evidence,
        extraction_confidence=0.9,
        status=status,
        original_extracted_value=thickness or depth or seam,
        fact_version=1,
    )
    db.add(row)
    db.flush()
    return row


def test_a_geological_fact_persistence(db_session):
    doc = _doc(db_session)
    _page(
        db_session,
        doc,
        5,
        "Borehole BH-99. Seam IV thickness 0.79 m. Barakar Formation. Lithology: sandstone.",
    )
    rows = extract_and_persist_geological_facts(db_session, doc)
    assert rows
    db_session.commit()
    stored = db_session.query(GeologicalFact).filter(GeologicalFact.document_id == doc.id).all()
    assert stored
    assert any(r.seam_name for r in stored) or any(r.borehole_id for r in stored)
    for r in stored:
        d = geological_fact_to_dict(r)
        assert d["source_document_id"] == doc.id
        assert d.get("domain") == "geological"
        assert d.get("metric_kind") or r.seam_name or r.borehole_id


def test_b_provenance_persistence(db_session):
    doc = _doc(db_session)
    row = _fact(
        db_session,
        doc,
        page=81,
        seam="Seam IV",
        thickness_min="0.54",
        thickness_max="1.22",
        metric_kind="seam_thickness",
        evidence="Seam IV thickness varies from 0.54 to 1.22 m",
    )
    db_session.commit()
    assert row.source_page == 81
    assert row.evidence_text
    assert row.document_id == doc.id
    assert row.thickness_min == "0.54"
    assert row.thickness_max == "1.22"
    assert row.original_value and "0.54" in row.original_value


def test_c_seam_fact_retrieval(db_session):
    doc = _doc(db_session, "block_a.pdf")
    _fact(db_session, doc, seam="Seam IV", metric_kind="seam", status=FactStatus.APPROVED.value)
    _fact(db_session, doc, seam="Seam III", metric_kind="seam", status=FactStatus.APPROVED.value)
    db_session.commit()
    plan = parse_query("What coal seams are reported in this report?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    values = {h.value for h in hits}
    assert any("IV" in (v or "") for v in values)
    assert any("III" in (v or "") for v in values)


def test_d_borehole_fact_retrieval(db_session):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        borehole="CMNPB-03",
        metric_kind="borehole",
        status=FactStatus.APPROVED.value,
    )
    db_session.commit()
    plan = parse_query("Which boreholes are mentioned?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert any(h.borehole_id and "CMNPB" in h.borehole_id.upper() for h in hits)


def test_e_formation_fact_retrieval(db_session):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        formation="Barakar Formation",
        metric_kind="formation",
        status=FactStatus.APPROVED.value,
    )
    db_session.commit()
    plan = parse_query("What formations are identified?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert any("Barakar" in (h.value or "") for h in hits)


def test_f_lithology_retrieval(db_session):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        lithology="sandstone",
        borehole="BH-01",
        metric_kind="lithology",
        status=FactStatus.APPROVED.value,
    )
    db_session.commit()
    plan = parse_query("What lithology is reported in the boreholes?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert any("sandstone" in (h.value or "").lower() for h in hits)


def test_g_seam_thickness_retrieval(db_session):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        seam="Seam IV",
        thickness_min="0.54",
        thickness_max="1.22",
        metric_kind="seam_thickness",
        status=FactStatus.APPROVED.value,
        evidence="Seam IV thickness 0.54–1.22 m",
    )
    _fact(
        db_session,
        doc,
        formation="Barakar Formation",
        thickness_min="150",
        thickness_max="250",
        metric_kind="formation_thickness",
        status=FactStatus.APPROVED.value,
        evidence="Barakar Formation thickness 150–250 m",
        page=71,
    )
    db_session.commit()
    plan = parse_query("What is the thickness of Seam IV?")
    assert plan.geological_seam
    assert "IV" in plan.geological_seam
    assert plan.metric == "seam_thickness" or "seam_thickness" in plan.geological_metrics
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert hits
    assert all(h.metric == "seam_thickness" for h in hits)
    assert all("150" not in (h.value or "") for h in hits)


def test_h_formation_thickness_retrieval(db_session):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        formation="Barakar Formation",
        thickness_min="150",
        thickness_max="250",
        metric_kind="formation_thickness",
        status=FactStatus.APPROVED.value,
        evidence="Barakar Formation thickness ranges 150 to 250 m",
    )
    _fact(
        db_session,
        doc,
        seam="Seam IV",
        thickness="0.79",
        metric_kind="seam_thickness",
        status=FactStatus.APPROVED.value,
        evidence="Seam IV thickness 0.79 m",
    )
    db_session.commit()
    plan = parse_query("What is the thickness of the Barakar Formation?")
    assert "formation_thickness" in (plan.geological_metrics or []) or plan.metric == "formation_thickness"
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert hits
    assert all(h.metric == "formation_thickness" for h in hits)


def test_i_metric_incompatibility_rejection(db_session):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        borehole="BH-01",
        depth="220",
        metric_kind="borehole_depth",
        status=FactStatus.APPROVED.value,
        evidence="Borehole BH-01 depth 220 m",
    )
    db_session.commit()
    plan = parse_query("What is the thickness of Seam IV?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert hits == []


def test_j_entity_safe_matching():
    assert seams_match("Seam IV", "seam IV")
    assert seams_match("Seam IV", "Seam IV")
    assert not seams_match("Seam I", "Seam II")
    assert not seams_match("Seam I", "Seam III")
    assert not seams_match("Seam I", "Seam VIA")
    assert boreholes_match("CMNPB-03", "cmnpb03")
    assert boreholes_match("CMNPB-03", "CMNPB-03")
    assert formations_match("Barakar Formation", "Barakar")
    assert not formations_match("Barakar", "Raniganj")


def test_k_document_scope(db_session):
    a = _doc(db_session, "report_a.pdf")
    b = _doc(db_session, "report_b.pdf")
    _fact(db_session, a, seam="Seam IV", metric_kind="seam", status=FactStatus.APPROVED.value)
    _fact(db_session, b, seam="Seam R4", metric_kind="seam", status=FactStatus.APPROVED.value)
    db_session.commit()
    plan = parse_query("What coal seams are reported in this report?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[a.id]
    )
    assert hits
    assert all(h.document_id == a.id for h in hits)
    assert not any("R4" in (h.value or "") for h in hits)


def test_l_explicit_comparison_entities():
    plan = parse_query("Compare Seam IV and Seam III.")
    assert plan.is_geological
    assert plan.comparison_mode == "compare" or plan.geological_intent == "comparison"
    assert len(plan.geological_seams) >= 2
    assert any("IV" in s for s in plan.geological_seams)
    assert any("III" in s for s in plan.geological_seams)


def test_m_review_required_status_preserved(db_session):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        seam="Seam R4",
        metric_kind="seam",
        status=FactStatus.REVIEW_REQUIRED.value,
    )
    db_session.commit()
    plan = parse_query("What coal seams are reported?")
    hits = retrieve_geological_facts(
        db_session,
        plan,
        verified_only=False,
        include_unverified=True,
        document_ids=[doc.id],
    )
    assert hits
    assert all(h.status == FactStatus.REVIEW_REQUIRED.value for h in hits)
    row = db_session.query(GeologicalFact).filter(GeologicalFact.document_id == doc.id).one()
    assert row.status == FactStatus.REVIEW_REQUIRED.value


def test_n_corrected_fact_history(db_session):
    doc = _doc(db_session)
    row = _fact(
        db_session,
        doc,
        seam="Seam IV",
        thickness="0.79",
        metric_kind="seam_thickness",
        status=FactStatus.REVIEW_REQUIRED.value,
    )
    db_session.commit()
    updated = review_geological_fact(
        db_session,
        row.id,
        action="correct",
        corrected_value="0.85",
        corrected_unit="m",
        reviewer="tester",
        reason="OCR misread",
    )
    db_session.commit()
    assert updated.status == FactStatus.CORRECTED.value
    assert updated.original_extracted_value
    assert updated.corrected_value == "0.85"
    assert updated.corrected_by == "tester"
    assert updated.correction_reason == "OCR misread"
    assert updated.fact_version >= 2
    assert updated.evidence_text


def test_o_geological_listing_query():
    plan = parse_query("What coal seams are reported in this report?")
    assert plan.is_geological
    assert plan.listing_intent or plan.geological_intent in {"seam", "seam_listing"}
    assert "seam" in (plan.geological_metrics or plan.metrics or [])


def test_p_geological_follow_up_query():
    plan = parse_query(
        "What is its thickness?",
        prior_seam="Seam IV",
    )
    assert plan.is_geological
    assert plan.geological_seam and "IV" in plan.geological_seam
    assert plan.metric == "seam_thickness" or "seam_thickness" in (
        plan.geological_metrics or []
    )


def test_q_geological_mining_routing():
    geo = parse_query("What coal seams were identified?")
    assert geo.is_geological and geo.domain == "geological"
    mining = parse_query("How much coal was produced by ECL?")
    assert not mining.is_geological
    thick = parse_query("What is the thickness of Seam IV?")
    assert thick.is_geological
    prod = parse_query("What was coal production?")
    assert not prod.is_geological or prod.domain == "mining"


def test_r_unsupported_geological_query(db_session):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        seam="Seam IV",
        thickness="0.79",
        metric_kind="seam_thickness",
        status=FactStatus.APPROVED.value,
    )
    db_session.commit()
    plan2 = parse_query("What is the depth of Borehole BH-999?")
    hits = retrieve_geological_facts(
        db_session, plan2, verified_only=True, document_ids=[doc.id]
    )
    assert hits == []


def test_s_duplicate_fact_handling(db_session):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        page=10,
        seam="Seam IV",
        metric_kind="seam",
        status=FactStatus.APPROVED.value,
    )
    _fact(
        db_session,
        doc,
        page=12,
        seam="Seam IV",
        metric_kind="seam",
        status=FactStatus.APPROVED.value,
    )
    db_session.commit()
    plan = parse_query("What coal seams are reported?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    seam_hits = [h for h in hits if h.metric == "seam"]
    keys = {(h.document_id, (h.value or "").lower()) for h in seam_hits}
    assert len(keys) == len(seam_hits)


def test_t_mining_regression_unchanged():
    plan = parse_query("What was CIL production in March FY25?")
    assert plan.is_geological is False
    assert plan.entity and "cil" in plan.entity.lower()
    assert "production" in (plan.metrics or []) or plan.metric == "production"


def test_query_borehole_depth_slots():
    plan = parse_query("What is the depth of Borehole CMNPB-03?")
    assert plan.is_geological
    assert plan.geological_borehole and "CMNPB" in plan.geological_borehole.upper()
    assert "borehole_depth" in (plan.geological_metrics or []) or plan.metric == "borehole_depth"


def test_query_formation_of_seam():
    plan = parse_query("Which formation contains Seam R4?")
    assert plan.is_geological
    assert plan.geological_seam and "R4" in plan.geological_seam.upper()


def test_assistant_preserves_review_warning(db_session, monkeypatch):
    doc = _doc(db_session)
    _fact(
        db_session,
        doc,
        seam="Seam R4",
        metric_kind="seam",
        status=FactStatus.REVIEW_REQUIRED.value,
    )
    db_session.commit()

    monkeypatch.setattr(
        "app.assistant.answer_generator.generate_answer",
        lambda *a, **k: "Extracted seams pending review.",
    )
    monkeypatch.setattr(
        "app.assistant.rag_retriever.retrieve_rag_evidence",
        lambda *a, **k: [],
    )
    out = ask_assistant(
        db_session,
        "What coal seams are reported in this report?",
        document_id=doc.id,
    )
    assert out
    row = db_session.query(GeologicalFact).filter(GeologicalFact.document_id == doc.id).one()
    assert row.status == FactStatus.REVIEW_REQUIRED.value


def _find_uploaded(name_substr: str) -> Path | None:
    roots = [
        Path(__file__).resolve().parents[1] / "backend" / "data" / "documents",
        Path(__file__).resolve().parents[1] / "data" / "documents",
        Path.home() / "mineintel-ai" / "backend" / "data" / "documents",
    ]
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.pdf"):
            if name_substr.lower() in p.name.lower():
                return p
    return None


@pytest.mark.parametrize(
    "substr,question",
    [
        ("Parbelia", "What coal seams are reported in this report?"),
        ("Sheetaldhara", "Which boreholes are mentioned?"),
        ("Labji", "What lithology is reported in the boreholes?"),
    ],
)
def test_real_document_generic_query_parse(substr, question):
    """Only asserts generic routing — never hard-codes expected seam/page answers."""
    path = _find_uploaded(substr)
    if path is None:
        pytest.skip(f"Uploaded PDF matching {substr!r} not found locally")
    plan = parse_query(question)
    assert plan.is_geological is True
    assert plan.domain == "geological"
