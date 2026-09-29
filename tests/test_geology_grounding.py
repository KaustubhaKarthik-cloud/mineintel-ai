"""Geological grounding: seam-associated ranges and conflict keys."""

from __future__ import annotations

from app.assistant.geological_retriever import (
    detect_geological_conflicts,
    prefer_multi_seam_thickness,
)
from app.assistant.query_router import QueryPlan, parse_query
from app.assistant.structured_retriever import StructuredFactHit
from app.geology.extractor import extract_facts_from_pages


def test_thickness_of_seam_keeps_document_entity():
    plan = parse_query(
        "What is the thickness of Seam III Bottom?",
        prior_entity="West of Sheetaldhara",
    )
    assert plan.is_geological
    assert "seam_thickness" in (plan.metrics or [])
    assert plan.entity and "sheetaldhara" in plan.entity.lower()
    assert "iii" not in (plan.entity or "").lower()


def test_extractor_associates_seam_and_preserves_range():
    pages = [
        (
            81,
            "The thickness of the seam IV varies within the block with general "
            "thickness varying from 0.54m to 1.22m.",
            None,
        ),
        (
            91,
            "The thickness of the seam III bottom varies within the block with "
            "general thickness varying from 0.55m to 0.85m.",
            None,
        ),
    ]
    drafts = extract_facts_from_pages(pages)
    ranges = [d for d in drafts if d.thickness_min and d.thickness_max]
    by_seam = {d.seam_name: d for d in ranges if d.seam_name}
    assert "Seam IV" in by_seam
    assert by_seam["Seam IV"].thickness_min == "0.54"
    assert by_seam["Seam IV"].thickness_max == "1.22"
    assert "Seam III Bottom" in by_seam
    assert by_seam["Seam III Bottom"].thickness_min == "0.55"
    assert by_seam["Seam III Bottom"].thickness_max == "0.85"


def test_conflict_does_not_flag_different_seams():
    hits = [
        StructuredFactHit(
            entity="Seam IV",
            metric="seam_thickness",
            period=None,
            value="0.54–1.22",
            numeric_value=0.54,
            unit="m",
            status="high_confidence",
            document_id="d1",
            document_name="doc.pdf",
            document_version=1,
            page=81,
            sheet_name=None,
            evidence_text="thickness of the seam IV ... 0.54m to 1.22m",
            fact_id="f1",
            confidence=0.9,
            seam_name="Seam IV",
            value_min="0.54",
            value_max="1.22",
            value_min_normalized=0.54,
            value_max_normalized=1.22,
        ),
        StructuredFactHit(
            entity="Seam III Bottom",
            metric="seam_thickness",
            period=None,
            value="0.55–0.85",
            numeric_value=0.55,
            unit="m",
            status="high_confidence",
            document_id="d1",
            document_name="doc.pdf",
            document_version=1,
            page=91,
            sheet_name=None,
            evidence_text="thickness of the seam III bottom ... 0.55m to 0.85m",
            fact_id="f2",
            confidence=0.9,
            seam_name="Seam III Bottom",
            value_min="0.55",
            value_max="0.85",
            value_min_normalized=0.55,
            value_max_normalized=0.85,
        ),
    ]
    assert detect_geological_conflicts(hits) == []


def test_prefer_one_range_per_seam():
    plan = QueryPlan(
        raw_question="What is the thickness of the coal seams?",
        query_type="hybrid",
        metrics=["seam_thickness"],
        is_geological=True,
        geological_metrics=["seam_thickness"],
        geological_intent="seam_thickness",
        domain="geological",
    )
    hits = [
        StructuredFactHit(
            entity="Seam IV",
            metric="seam_thickness",
            period=None,
            value="0.60",
            numeric_value=0.6,
            unit="m",
            status="review_required",
            document_id="d1",
            document_name="doc.pdf",
            document_version=1,
            page=81,
            sheet_name=None,
            evidence_text="min 0.60",
            fact_id="a",
            confidence=0.7,
            seam_name="Seam IV",
        ),
        StructuredFactHit(
            entity="Seam IV",
            metric="seam_thickness",
            period=None,
            value="0.54–1.22",
            numeric_value=0.54,
            unit="m",
            status="high_confidence",
            document_id="d1",
            document_name="doc.pdf",
            document_version=1,
            page=81,
            sheet_name=None,
            evidence_text="0.54 to 1.22",
            fact_id="b",
            confidence=0.95,
            seam_name="Seam IV",
            value_min="0.54",
            value_max="1.22",
            value_min_normalized=0.54,
            value_max_normalized=1.22,
        ),
    ]
    out = prefer_multi_seam_thickness(hits, plan)
    assert len(out) == 1
    assert out[0].value_min == "0.54"
    assert out[0].value_max == "1.22"
