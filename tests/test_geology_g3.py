"""G3 — Geological evidence-grounded Q&A, validation, and conflict detection.

Programmatic fixtures only — no hard-coded document answers.
"""

from __future__ import annotations

from unittest.mock import patch

from app.assistant.answer_generator import GEOLOGICAL_SYSTEM_PROMPT, generate_answer
from app.assistant.evidence_builder import EvidencePack
from app.assistant.evidence_filter import evidence_compatible
from app.assistant.geological_retriever import detect_geological_conflicts, retrieve_geological_facts
from app.assistant.query_router import parse_query
from app.assistant.service import ask_assistant
from app.assistant.structured_retriever import StructuredFactHit
from app.geology.validation import (
    conflicts_as_dicts,
    metrics_are_comparable,
    validate_geological_hit,
)
from app.models import Document, FactStatus, GeologicalFact, IndexStatus


def _hit(
    *,
    doc_id: str = "doc-a",
    doc_name: str = "ReportA.pdf",
    seam: str | None = "Seam R4",
    metric: str = "seam_thickness",
    value: str = "0.90",
    unit: str = "m",
    page: int = 10,
    status: str = "approved",
    fact_id: str = "f1",
    borehole: str | None = None,
    formation: str | None = None,
    numeric: float | None = 0.90,
    vmin: str | None = None,
    vmax: str | None = None,
    evidence: str = "synthetic",
) -> StructuredFactHit:
    return StructuredFactHit(
        entity=seam or doc_name,
        metric=metric,
        period=None,
        value=value,
        numeric_value=numeric,
        unit=unit,
        status=status,
        document_id=doc_id,
        document_name=doc_name,
        document_version=1,
        page=page,
        sheet_name=None,
        evidence_text=evidence,
        fact_id=fact_id,
        confidence=0.9,
        seam_name=seam,
        borehole_id=borehole,
        geological_formation=formation,
        value_min=vmin,
        value_max=vmax,
    )


def _doc(db, name="g3_synth.pdf") -> Document:
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


def test_missing_r4_thickness_insufficient(db_session):
    doc = _doc(db_session)
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            metric_kind="minimum_workable_seam_thickness",
            thickness="0.90",
            thickness_unit="m",
            source_page=28,
            evidence_text="minimum workable thickness is 0.90m",
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.9,
        )
    )
    db_session.commit()
    plan = parse_query("What is the thickness of Seam R4?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert hits == []


def test_generic_thickness_cannot_answer_r4():
    plan = parse_query("What is the thickness of Seam R4?")
    bad = evidence_compatible(
        plan,
        "combustible bands below 100 cm thickness are discarded",
        require_metric=True,
    )
    assert not bad.ok
    # Long-page co-occurrence: R4 elsewhere + methodology 100 cm must still fail
    long_page = (
        "Potentiality of seam R4 of Raniganj Formation has been established. "
        "Later section: 100 cm thickness and excluding shale (non-combustible bands) "
        "& other obvious dirt bands like sandstone. DATA SYNTHESIS follows."
    )
    assert not evidence_compatible(plan, long_page, require_metric=True).ok


def test_formation_thickness_not_seam_thickness():
    assert not metrics_are_comparable("seam_thickness", "formation_thickness")
    plan = parse_query("What is the thickness of Seam R4?")
    bad = evidence_compatible(
        plan,
        "The average thickness of the Barakar Formation is 150 to 250 m",
        require_metric=True,
    )
    assert not bad.ok


def test_other_seam_cannot_answer_r4(db_session):
    doc = _doc(db_session)
    db_session.add(
        GeologicalFact(
            document_id=doc.id,
            metric_kind="seam_thickness",
            seam_name="Seam III",
            seam_status="named",
            thickness="1.20",
            thickness_unit="m",
            source_page=12,
            evidence_text="Seam III thickness 1.20 m",
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.9,
        )
    )
    db_session.commit()
    plan = parse_query("What is the thickness of Seam R4?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[doc.id]
    )
    assert hits == []


def test_other_document_blocked_by_scope(db_session):
    a = _doc(db_session, "a.pdf")
    b = _doc(db_session, "b.pdf")
    db_session.add(
        GeologicalFact(
            document_id=b.id,
            metric_kind="seam",
            seam_name="Seam R4",
            seam_status="named",
            source_page=1,
            evidence_text="Seam R4 present",
            status=FactStatus.APPROVED.value,
            extraction_confidence=0.9,
        )
    )
    db_session.commit()
    plan = parse_query("What coal seams are identified in this report?")
    hits = retrieve_geological_facts(
        db_session, plan, verified_only=True, document_ids=[a.id]
    )
    assert hits == []


def test_qwen_prompt_forbids_invention():
    assert "Do NOT invent" in GEOLOGICAL_SYSTEM_PROMPT
    assert "review_required" in GEOLOGICAL_SYSTEM_PROMPT


def test_review_required_preserved_in_pack():
    plan = parse_query("What coal seams are identified?")
    hit = _hit(status="review_required", metric="seam", value="Seam R4", numeric=None)
    pack = EvidencePack(plan=plan, structured=[hit])
    ctx = pack.to_prompt_context()
    assert "review_required" in ctx


def test_ranges_preserved_in_prompt():
    a = _hit(value="0.90–1.20", vmin="0.90", vmax="1.20", numeric=None, fact_id="a")
    pack = EvidencePack(
        plan=parse_query("What is the thickness of Seam R4?"),
        structured=[a],
    )
    ctx = pack.to_prompt_context()
    assert "0.90" in ctx and "1.20" in ctx


def test_mock_answer_no_evidence_does_not_invent():
    plan = parse_query("What is the thickness of Seam R4?")
    pack = EvidencePack(plan=plan)
    text = generate_answer(pack)
    low = text.lower()
    assert "insufficient" in low or "not found" in low
    assert "1.20" not in text and "0.90" not in text


def test_same_seam_same_metric_conflict():
    a = _hit(value="0.90", numeric=0.90, page=10, fact_id="a1")
    b = _hit(value="1.20", numeric=1.20, page=12, fact_id="a2")
    conflicts = detect_geological_conflicts([a, b])
    assert conflicts
    assert conflicts[0]["conflict_type"] == "geological_value_mismatch"
    assert conflicts[0]["requires_human_review"] is True
    assert len(conflicts[0]["evidence"]) == 2


def test_different_seam_no_conflict():
    a = _hit(seam="Seam R4", value="0.90", numeric=0.90, fact_id="a")
    b = _hit(seam="Seam III", value="1.20", numeric=1.20, fact_id="b")
    assert detect_geological_conflicts([a, b]) == []


def test_different_metric_no_conflict():
    a = _hit(metric="seam_thickness", value="0.90", numeric=0.90, fact_id="a")
    b = _hit(metric="formation_thickness", value="150", numeric=150, seam=None, fact_id="b")
    assert detect_geological_conflicts([a, b]) == []


def test_workable_vs_seam_thickness_no_conflict():
    a = _hit(metric="seam_thickness", value="1.05", numeric=1.05, fact_id="a")
    b = _hit(
        metric="minimum_workable_seam_thickness",
        value="0.90",
        numeric=0.90,
        seam=None,
        fact_id="b",
    )
    assert detect_geological_conflicts([a, b]) == []
    assert not metrics_are_comparable("seam_thickness", "minimum_workable_seam_thickness")


def test_cross_document_discrepancy_not_contradiction():
    a = _hit(doc_id="doc-a", doc_name="A.pdf", value="0.90", numeric=0.90, fact_id="a")
    b = _hit(doc_id="doc-b", doc_name="B.pdf", value="1.20", numeric=1.20, fact_id="b")
    conflicts = detect_geological_conflicts([a, b])
    assert conflicts
    assert conflicts[0]["conflict_type"] == "cross_document_discrepancy"
    assert conflicts[0]["requires_human_review"] is True


def test_different_boreholes_no_conflict():
    a = _hit(borehole="CMNPB-01", value="0.85", numeric=0.85, fact_id="a")
    b = _hit(borehole="CMNPB-02", value="1.10", numeric=1.10, fact_id="b")
    assert detect_geological_conflicts([a, b]) == []


def test_same_borehole_same_seam_conflict():
    a = _hit(borehole="CMNPB-01", value="0.85", numeric=0.85, fact_id="a", page=5)
    b = _hit(borehole="CMNPB-01", value="1.10", numeric=1.10, fact_id="b", page=6)
    conflicts = detect_geological_conflicts([a, b])
    assert conflicts
    assert conflicts[0]["conflict_type"] == "geological_value_mismatch"


def test_range_contains_point_not_conflict():
    a = _hit(
        value="0.90–1.20",
        vmin="0.90",
        vmax="1.20",
        numeric=None,
        fact_id="a",
    )
    a.value_min_normalized = 0.90
    a.value_max_normalized = 1.20
    b = _hit(value="1.05", numeric=1.05, fact_id="b")
    b.value_min_normalized = 1.05
    b.value_max_normalized = 1.05
    assert detect_geological_conflicts([a, b]) == []


def test_validate_workable_mislabelled():
    h = _hit(
        metric="seam_thickness",
        evidence="The minimum workable thickness is 0.90m for the seam",
    )
    issues = validate_geological_hit(h)
    assert any(i.code == "workable_mislabelled_as_seam_thickness" for i in issues)


def test_ask_surfaces_conflict_without_picking_winner(db_session):
    doc = _doc(db_session)
    for val, page in [("0.90", 10), ("1.20", 12)]:
        db_session.add(
            GeologicalFact(
                document_id=doc.id,
                metric_kind="seam_thickness",
                seam_name="Seam R4",
                seam_status="named",
                thickness=val,
                thickness_unit="m",
                thickness_normalized_m=float(val),
                source_page=page,
                evidence_text=f"Seam R4 thickness {val} m",
                status=FactStatus.APPROVED.value,
                extraction_confidence=0.95,
            )
        )
    db_session.commit()

    with patch(
        "app.assistant.answer_generator.generate_answer",
        lambda pack, provider=None: "Conflict note placeholder",
    ):
        with patch("app.assistant.rag_retriever.retrieve_rag_evidence", lambda *a, **k: []):
            out = ask_assistant(
                db_session,
                "What is the thickness of Seam R4?",
                document_id=doc.id,
            )
    assert out.get("is_geological") is True
    conflicts = out.get("conflicts") or []
    assert conflicts or len(out.get("structured_evidence") or []) >= 2
    if conflicts:
        assert any(c.get("requires_human_review") for c in conflicts)


def test_mining_regression_routing():
    for q in (
        "What was CIL production in March FY25?",
        "How much coal did ECL produce in FY25?",
        "What was BCCL production?",
        "CCL coal production FY25",
        "Captive/Others production in March FY25",
    ):
        plan = parse_query(q)
        assert plan.is_geological is False, q


def test_conflicts_as_dicts_api_shape():
    a = _hit(value="0.90", numeric=0.90, fact_id="x1")
    b = _hit(value="1.50", numeric=1.50, fact_id="x2")
    dicts = conflicts_as_dicts([a, b])
    assert dicts
    keys = set(dicts[0])
    assert {
        "id",
        "conflict_type",
        "entity_name",
        "field_name",
        "status",
        "evidence",
        "requires_human_review",
    } <= keys
