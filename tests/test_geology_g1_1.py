"""G1.1 — Geological query routing, coal-vs-seam disambiguation, evidence filter."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.assistant.evidence_filter import evidence_compatible
from app.assistant.geological_retriever import retrieve_geological_facts
from app.assistant.query_router import parse_query
from app.assistant.rag_retriever import retrieve_rag_evidence
from app.assistant.service import ask_assistant
from app.models import Document, FactStatus, GeologicalFact


def test_a_coal_seams_geological_not_mining_coal():
    plan = parse_query("What coal seams are identified in the exploration report?")
    assert plan.is_geological is True
    assert plan.domain == "geological"
    assert plan.geological_intent in {"seam", "seam_listing", "geological"}
    assert "coal" not in (plan.metrics or [])
    assert plan.metric != "coal"
    assert "seam" in (plan.metrics or []) or "seam" in (plan.geological_metrics or [])


def test_b_seam_thickness_intent():
    plan = parse_query("What is the thickness of the coal seams?")
    assert plan.is_geological is True
    assert "seam_thickness" in (plan.metrics or []) or plan.metric == "seam_thickness"
    assert "coal" not in (plan.metrics or [])


def test_c_borehole_intent():
    plan = parse_query("Which boreholes are mentioned in the report?")
    assert plan.is_geological is True
    assert plan.geological_intent == "borehole" or "borehole" in (plan.metrics or [])


def test_d_lithology_intent():
    plan = parse_query("What lithology is reported?")
    assert plan.is_geological is True
    assert "lithology" in (plan.metrics or []) or plan.metric == "lithology"


def test_e_formation_intent():
    plan = parse_query("What formations are identified?")
    assert plan.is_geological is True
    assert "formation" in (plan.metrics or []) or plan.metric == "formation"


def test_f_mining_coal_production_intent():
    plan = parse_query("How much coal did ECL produce in FY25?")
    assert plan.is_geological is False
    assert plan.domain == "mining" or "coal" in (plan.metrics or []) or plan.metric == "coal"
    assert plan.entity and "ecl" in plan.entity.lower()
    assert any("2025" in p or p.endswith("25") for p in plan.periods)


def test_g_mining_cil_march_unchanged():
    plan = parse_query("What was CIL production in March FY25?")
    assert plan.is_geological is False
    assert plan.entity and "cil" in plan.entity.lower()
    assert "production" in (plan.metrics or []) or plan.metric == "production"
    assert plan.reporting_months and any(m.lower().startswith("mar") for m in plan.reporting_months)
    assert any("2025" in p for p in plan.periods)


def test_entity_strips_exploration_report_suffix():
    plan = parse_query(
        "What coal seams are identified in the West of Sheetaldhara exploration report?"
    )
    assert plan.is_geological is True
    assert plan.entity
    assert "exploration" not in plan.entity.lower()
    assert "report" not in plan.entity.lower()
    assert "sheetaldhara" in plan.entity.lower()
    assert "coal" not in (plan.metrics or [])


def test_geological_evidence_skips_mining_factual_role():
    plan = parse_query(
        "What coal seams are identified in the West of Sheetaldhara exploration report?"
    )
    chunk = (
        "The exploration drilling in the West of Sheetaldhara Block revealed presence "
        "of many correlatable local coal seam horizons, which have been encountered "
        "throughout the block viz. IIL, IL and L1."
    )
    compat = evidence_compatible(
        plan,
        chunk,
        require_entity=True,
        require_metric=True,
        meta={"document_name": "West_of_Sheetaldhara.pdf"},
    )
    assert compat.ok, compat.reasons
    assert "entity_not_factual_subject" not in compat.reasons
    assert "geological_path" in compat.reasons


def test_mining_evidence_still_requires_factual_role():
    plan = parse_query("How much coal did Telangana produce in FY25?")
    boilerplate = (
        "Telangana is bordered by several states. FY2025 calendar notes appear below. "
        "Coal seams are discussed in an unrelated appendix."
    )
    reject = evidence_compatible(plan, boilerplate, require_entity=True, require_metric=True)
    # Must not accept mere mention without production factual role
    assert not reject.ok
    assert "entity_not_factual_subject" in reject.reasons or "metric_mismatch" in reject.reasons


def test_h_missing_borehole_insufficient(client, tmp_path, db_session):
    """Unsupported BH-999 → insufficient compatible evidence when not in corpus."""
    pdf = tmp_path / "geo_lab.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (40, 72),
        "Geological report. Borehole BH-27 intersected Seam III. Lithology: sandstone.",
        fontsize=10,
    )
    doc.save(pdf)
    doc.close()

    with pdf.open("rb") as f:
        up = client.post(
            "/api/documents/upload",
            files={"file": (pdf.name, f, "application/pdf")},
            data={"mine_name": "Lab"},
        )
    assert up.status_code == 200, up.text
    doc_id = up.json()["id"]
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200

    q = "What is the thickness of Borehole BH-999?"
    plan = parse_query(q)
    assert plan.is_geological is True

    hits = retrieve_rag_evidence(db_session, q, plan=plan)
    # Either no hits, or none mentioning BH-999 (filter rejects)
    assert all("BH-999" not in (h.text or "").upper().replace(" ", "") for h in hits) or not hits

    result = ask_assistant(db_session, q)
    reply = (result.get("reply") or result.get("answer") or "").lower()
    assert "insufficient" in reply or "couldn't find" in reply or "could not find" in reply or not result.get("rag_evidence")


def test_geological_verified_facts_preferred_over_review(db_session, tmp_path):
    """review_required must not be returned as verified structured geo facts."""
    doc = Document(
        filename="geo.pdf",
        original_filename="geo_block.pdf",
        file_path=str(tmp_path / "geo.pdf"),
        file_type="pdf",
        status="extracted",
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            seam_name="Seam R4",
            evidence_text="Seam R4 mentioned pending review",
            source_page=1,
            extraction_confidence=0.5,
            status=FactStatus.REVIEW_REQUIRED.value,
        )
    )
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            seam_name="Seam IV",
            evidence_text="Seam IV at high confidence",
            source_page=2,
            extraction_confidence=0.9,
            status=FactStatus.HIGH_CONFIDENCE.value,
        )
    )
    db_session.commit()

    plan = parse_query("What coal seams are identified in the geo block report?")
    plan.entity = "geo block"
    hits = retrieve_geological_facts(db_session, plan, verified_only=True)
    names = {h.value for h in hits}
    assert "Seam IV" in names
    assert "Seam R4" not in names

    mixed = retrieve_geological_facts(
        db_session, plan, verified_only=False, include_unverified=True
    )
    mixed_names = {h.value for h in mixed}
    assert "Seam IV" in mixed_names
    assert "Seam R4" in mixed_names
    review = next(h for h in mixed if h.value == "Seam R4")
    assert review.status == FactStatus.REVIEW_REQUIRED.value
