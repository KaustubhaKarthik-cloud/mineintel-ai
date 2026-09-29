"""Metric taxonomy + document scope for geological thickness queries (no hard-codes)."""

from __future__ import annotations

from app.assistant.document_resolver import resolve_document_scope
from app.assistant.evidence_filter import evidence_compatible
from app.assistant.query_router import parse_query
from app.geology.extractor import extract_facts_from_page
from app.geology.metric_kinds import (
    FORMATION_THICKNESS,
    SEAM_PARTING_THICKNESS,
    SEAM_THICKNESS,
    classify_evidence_metric_kind,
    classify_query_thickness_metric,
    metrics_compatible,
)
from app.models import Document, IndexStatus


def test_a_query_metric_seam_thickness():
    assert classify_query_thickness_metric(
        "What is the thickness of the coal seams?"
    ) == SEAM_THICKNESS
    plan = parse_query("What is the thickness of the coal seams in this report?")
    assert plan.is_geological
    assert plan.geological_metrics[0] == "seam_thickness"
    assert "formation_thickness" not in plan.geological_metrics


def test_b_query_metric_formation_thickness():
    assert classify_query_thickness_metric(
        "What is the thickness of the Barakar Formation?"
    ) == FORMATION_THICKNESS
    plan = parse_query("What is the thickness of the Barakar Formation?")
    assert plan.geological_metrics[0] == "formation_thickness"
    assert "seam_thickness" not in plan.geological_metrics


def test_c_query_metric_parting():
    assert classify_query_thickness_metric(
        "What is the thickness of the parting?"
    ) == SEAM_PARTING_THICKNESS
    plan = parse_query("What is the thickness of the parting?")
    assert plan.geological_metrics[0] == "seam_parting_thickness"


def test_d_query_metric_seam_iv():
    assert classify_query_thickness_metric("How thick is Seam IV?") == SEAM_THICKNESS
    plan = parse_query("What is the thickness of Seam IV?")
    assert plan.geological_metrics[0] == "seam_thickness"


def test_e_evidence_kind_rejects_formation_for_seam():
    text = (
        "The average thickness of the Barakar Formation of the block is 150-250m."
    )
    kind = classify_evidence_metric_kind(
        text=text,
        geological_formation="Barakar Formation",
        has_thickness=True,
        requested=SEAM_THICKNESS,
    )
    assert kind == FORMATION_THICKNESS
    assert not metrics_compatible(SEAM_THICKNESS, kind)


def test_f_evidence_kind_allows_seam_thickness():
    text = "Thickness of the seam IV varies from 0.54m to 1.22m within the block."
    kind = classify_evidence_metric_kind(
        text=text,
        seam_name="Seam IV",
        has_thickness=True,
        requested=SEAM_THICKNESS,
    )
    assert kind == SEAM_THICKNESS
    assert metrics_compatible(SEAM_THICKNESS, kind)


def test_g_filter_rejects_formation_rag_for_seam_query():
    plan = parse_query("What is the thickness of the coal seams in this report?")
    plan.scoped_document_ids = ["doc-a"]
    formation = (
        "The average thickness of the Barakar Formation of West block is 150-250m."
    )
    result = evidence_compatible(
        plan,
        formation,
        require_entity=False,
        require_metric=True,
        meta={"document_id": "doc-a", "document_name": "Report.pdf"},
    )
    assert not result.ok
    assert any("metric_kind_incompatible" in r or "metric_mismatch" in r for r in result.reasons)


def test_h_filter_allows_seam_rag():
    plan = parse_query("What is the thickness of the coal seams in this report?")
    plan.scoped_document_ids = ["doc-a"]
    seam_text = (
        "The thickness of the coal seams varies; Seam IV general thickness 0.54m to 1.22m."
    )
    result = evidence_compatible(
        plan,
        seam_text,
        require_entity=False,
        require_metric=True,
        meta={"document_id": "doc-a", "document_name": "Report.pdf", "seam_name": "Seam IV"},
    )
    assert result.ok


def test_i_scope_current_document_only(db_session):
    a = Document(
        id="met-a",
        filename="a.pdf",
        original_filename="Alpha_Geo_Report.pdf",
        file_path="/tmp/a.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    b = Document(
        id="met-b",
        filename="b.pdf",
        original_filename="Beta_Geo_Report.pdf",
        file_path="/tmp/b.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db_session.add_all([a, b])
    db_session.commit()

    scope = resolve_document_scope(
        db_session,
        question="What is the thickness of the coal seams in this report?",
        entity=None,
        current_document_id="met-a",
        is_geological=True,
    )
    assert scope.mode == "single_document"
    assert "met-a" in scope.allowed_ids
    assert "met-b" not in scope.allowed_ids
    assert scope.allowed_ids == ["met-a"]


def test_j_scope_cross_document_compare(db_session):
    a = Document(
        id="cmp-a",
        filename="cmpa.pdf",
        original_filename="North_Sample_Block.pdf",
        file_path="/tmp/cmpa.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    b = Document(
        id="cmp-b",
        filename="cmpb.pdf",
        original_filename="West_Sample_Block.pdf",
        file_path="/tmp/cmpb.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db_session.add_all([a, b])
    db_session.commit()

    scope = resolve_document_scope(
        db_session,
        question="Compare the coal seam thicknesses in North Sample and West Sample.",
        entity="North Sample",
        entities=["North Sample", "West Sample"],
        current_document_id="cmp-a",
        is_geological=True,
    )
    assert scope.mode == "cross_document_comparison"
    assert "cmp-a" in scope.allowed_ids
    assert "cmp-b" in scope.allowed_ids


def test_k_scope_switch_changes_allowed(db_session):
    a = Document(
        id="swm-a",
        filename="swma.pdf",
        original_filename="Switch_Alpha.pdf",
        file_path="/tmp/swma.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    b = Document(
        id="swm-b",
        filename="swmb.pdf",
        original_filename="Switch_Beta.pdf",
        file_path="/tmp/swmb.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db_session.add_all([a, b])
    db_session.commit()
    q = "What is the thickness of the coal seams in this report?"
    s1 = resolve_document_scope(
        db_session, question=q, entity=None, current_document_id="swm-a", is_geological=True
    )
    s2 = resolve_document_scope(
        db_session, question=q, entity=None, current_document_id="swm-b", is_geological=True
    )
    assert set(s1.allowed_ids).isdisjoint(set(s2.allowed_ids))


def test_l_extractor_formation_thickness_not_seam():
    text = (
        "The average thickness of the Barakar Formation of the block is 150-250m. "
        "Sandstone and shale dominate."
    )
    facts = extract_facts_from_page(text, page_number=71)
    formation = [f for f in facts if f.metric_kind == "formation_thickness"]
    assert formation, "expected formation_thickness fact"
    assert all(f.seam_name is None for f in formation)
    assert all(f.geological_formation and "Formation" in f.geological_formation for f in formation)
    # Must not also invent a seam thickness from the same span
    seam_thick = [
        f
        for f in facts
        if f.seam_name and (f.thickness or f.thickness_min) and f.metric_kind != "formation_thickness"
    ]
    assert not any(
        f.thickness_min == "150" or (f.thickness or "").startswith("150") for f in seam_thick
    )


def test_m_borehole_depth_metric():
    plan = parse_query("How deep was Borehole CMBJ087?")
    assert plan.is_geological
    assert plan.geological_metrics[0] == "borehole_depth"


def test_n_formation_query_allows_formation_evidence():
    plan = parse_query("What is the thickness of the Barakar Formation?")
    text = "The average thickness of the Barakar Formation of the block is 150-250m."
    result = evidence_compatible(
        plan,
        text,
        require_entity=False,
        require_metric=True,
        meta={"geological_formation": "Barakar Formation"},
    )
    assert result.ok
