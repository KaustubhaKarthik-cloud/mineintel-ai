"""G3.1 — formation quality, resource intent, selected-document scope.

Programmatic fixtures only — no hard-coded document answers.
"""

from __future__ import annotations

from unittest.mock import patch

from app.assistant.document_resolver import (
    is_cross_document_query,
    resolve_document_scope,
)
from app.assistant.evidence_builder import EvidencePack
from app.assistant.evidence_filter import evidence_compatible
from app.assistant.geological_retriever import retrieve_geological_facts
from app.assistant.query_router import parse_query
from app.assistant.service import ask_assistant
from app.geology.entities import (
    extract_formations_from_text,
    is_plausible_formation_name,
    normalize_formation_name,
)
from app.geology.extractor import extract_facts_from_page
from app.models import Document, FactStatus, GeologicalFact, IndexStatus


def _doc(db, name="g31_synth.pdf") -> Document:
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


def test_valid_formation_extraction():
    text = (
        "The Raniganj Formation and the Barakar Formation host coal seams. "
        "Talchir Formation underlies the sequence. Damuda Formation is also noted."
    )
    names = extract_formations_from_text(text)
    assert "Raniganj Formation" in names
    assert "Barakar Formation" in names
    assert "Talchir Formation" in names
    assert "Damuda Formation" in names


def test_invalid_formation_phrase_rejection():
    for frag in (
        "through the Formation",
        "lithology of Formation",
        "guide to Formation",
        "coaly Formation",
        "separate carbonaceous Formation",
        "geological Formation",
        "interpreted Formation",
        "the Formation",
        "this Formation",
        "above Formation",
        "below Formation",
    ):
        assert extract_formations_from_text(frag) == [], frag
        assert not is_plausible_formation_name(frag.replace(" Formation", ""), context=frag), frag


def test_formation_normalization():
    assert normalize_formation_name("raniganj formation") == "Raniganj Formation"
    assert normalize_formation_name("BARAKAR FORMATION") == "Barakar Formation"
    assert normalize_formation_name("Upper Raniganj") == "Upper Raniganj Formation"


def test_formation_deduplication_across_pages(db_session):
    doc = _doc(db_session)
    for page in (11, 27, 33):
        db_session.add(
            GeologicalFact(
                document_id=doc.id,
                metric_kind="formation",
                geological_formation="Raniganj Formation",
                source_page=page,
                evidence_text=f"Raniganj Formation noted on page {page}",
                status=FactStatus.APPROVED.value,
                extraction_confidence=0.9,
            )
        )
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            metric_kind="formation",
            geological_formation="through the Formation",
            source_page=12,
            evidence_text="passed through the Formation boundary",
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.5,
        )
    )
    db_session.commit()
    plan = parse_query("What formations are present in this report?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    names = [h.value for h in hits]
    assert names.count("Raniganj Formation") == 1
    assert not any("through" in (n or "").lower() for n in names)


def test_formation_listing_from_extractor():
    text = (
        "Stratigraphy: Raniganj Formation overlies Barakar Formation. "
        "through the Formation; lithology of Formation; coaly Formation."
    )
    drafts = extract_facts_from_page(text, page_number=5)
    fms = {
        d.geological_formation
        for d in drafts
        if d.geological_formation and (d.metric_kind or "") == "formation"
    }
    assert "Raniganj Formation" in fms
    assert "Barakar Formation" in fms
    assert not any("through" in (f or "").lower() for f in fms)
    assert not any("coaly" in (f or "").lower() for f in fms)


def test_resource_intent_and_seam_preserved():
    plan = parse_query("What is the inferred resource for Seam R4?")
    assert plan.is_geological is True
    assert plan.domain == "geological"
    assert plan.geological_intent == "resource"
    assert plan.metrics[0] == "resource"
    assert plan.geological_seam == "Seam R4"
    assert plan.listing_intent is False


def test_resource_not_confused_with_reserve():
    p_res = parse_query("What resource is reported for this seam?")
    assert p_res.metrics[0] == "resource"
    p_rev = parse_query("What is the proved reserve for Seam R4?")
    assert p_rev.metrics[0] == "reserve"
    assert p_rev.geological_seam == "Seam R4"


def test_current_document_scope_for_generic_metric(db_session):
    a = _doc(db_session, "Report_Alpha.pdf")
    b = _doc(db_session, "Report_Beta.pdf")
    for doc, page, val in ((a, 28, "0.90"), (b, 118, "0.75")):
        db_session.add(
            GeologicalFact(
                document_id=doc.id,
                metric_kind="minimum_workable_seam_thickness",
                thickness=val,
                thickness_unit="m",
                thickness_normalized_m=float(val),
                source_page=page,
                evidence_text=f"minimum workable thickness is {val}m",
                status=FactStatus.APPROVED.value,
                extraction_confidence=0.95,
            )
        )
    db_session.commit()

    q = "What is the minimum workable thickness?"
    plan = parse_query(q)
    scope = resolve_document_scope(
        db_session,
        question=q,
        entity=plan.entity,
        entities=plan.entities,
        current_document_id=a.id,
        is_geological=True,
    )
    assert scope.mode == "single_document"
    assert scope.allowed_ids == [a.id]
    assert b.id not in scope.allowed_ids

    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=scope.allowed_ids
    )
    assert hits
    assert all(h.document_id == a.id for h in hits)
    assert not any(h.document_id == b.id for h in hits)


def test_explicit_cross_document_comparison_allowed():
    q = "Compare the minimum workable thickness between North Parbelia and West Sheetaldhara."
    assert is_cross_document_query(q) is True
    plan = parse_query(q)
    assert plan.geological_intent == "comparison"
    assert plan.metrics[0] == "minimum_workable_seam_thickness"


def test_final_evidence_scope_in_ask(db_session):
    a = _doc(db_session, "Scoped_A.pdf")
    b = _doc(db_session, "Scoped_B.pdf")
    for doc, page, val in ((a, 10, "0.90"), (b, 20, "1.10")):
        db_session.add(
            GeologicalFact(
                document_id=doc.id,
                metric_kind="minimum_workable_seam_thickness",
                thickness=val,
                thickness_unit="m",
                thickness_normalized_m=float(val),
                source_page=page,
                evidence_text=f"minimum workable thickness is {val}m",
                status=FactStatus.APPROVED.value,
                extraction_confidence=0.95,
            )
        )
    db_session.commit()

    with patch(
        "app.assistant.answer_generator.generate_answer",
        lambda pack, provider=None: "scoped answer",
    ):
        with patch("app.assistant.rag_retriever.retrieve_rag_evidence", lambda *a, **k: []):
            out = ask_assistant(
                db_session,
                "What is the minimum workable thickness?",
                document_id=a.id,
            )
    docs = {e.get("source") or e.get("document") for e in (out.get("structured_evidence") or [])}
    docs |= {e.get("document") for e in (out.get("rag_evidence") or [])}
    assert docs <= {"Scoped_A.pdf", None}
    assert "Scoped_B.pdf" not in docs


def test_qwen_prompt_only_sees_scoped_evidence():
    plan = parse_query("What is the minimum workable thickness?")
    from app.assistant.structured_retriever import StructuredFactHit

    hit = StructuredFactHit(
        entity="Scoped_A.pdf",
        metric="minimum_workable_seam_thickness",
        period=None,
        value="0.90",
        numeric_value=0.90,
        unit="m",
        status="approved",
        document_id="doc-a",
        document_name="Scoped_A.pdf",
        document_version=1,
        page=28,
        sheet_name=None,
        evidence_text="minimum workable thickness is 0.90m",
        fact_id="f1",
        confidence=0.9,
    )
    pack = EvidencePack(plan=plan, structured=[hit])
    ctx = pack.to_prompt_context()
    assert "Scoped_A.pdf" in ctx
    assert "Sheetaldhara" not in ctx
    assert "0.90" in ctx


def test_g3_thickness_guard_regression():
    plan = parse_query("What is the thickness of Seam R4?")
    assert not evidence_compatible(
        plan,
        "combustible bands below 100 cm thickness are discarded",
        require_metric=True,
    ).ok
    assert not evidence_compatible(
        plan,
        "The average thickness of the Barakar Formation is 150 to 250 m",
        require_metric=True,
    ).ok
    assert not evidence_compatible(
        plan,
        "The minimum workable thickness is 0.90m for the seam",
        require_metric=True,
    ).ok


def test_mining_routing_regression():
    for q in (
        "What was CIL production in March FY25?",
        "ECL coal production FY25",
        "BCCL production",
        "CCL production March",
        "Captive/Others production March FY25",
    ):
        plan = parse_query(q)
        assert plan.is_geological is False, q
