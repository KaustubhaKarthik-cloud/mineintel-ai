"""Phase 7.1 — multi-fact reasoning tests (generic, no hard-coded org answers)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.assistant.multi_fact import (
    NormalizedFact,
    absolute_change,
    facts_from_rag_hits,
    format_multi_fact_answer,
    percentage_change,
    reason_over_facts,
    resolve_unique_facts,
    units_compatible,
)
from app.assistant.query_router import parse_query
from app.assistant.rag_retriever import RagHit, retrieve_rag_evidence
from app.assistant.service import ask_assistant
from tests.test_structured_table_pipeline import build_production_table_pdf


def _fact(**kwargs) -> NormalizedFact:
    base = dict(
        entity="Alpha Co",
        metric="coal",
        period="March",
        fy="FY2025",
        measure="during",
        value=10.0,
        unit="MT",
        source_document="t.pdf",
        page=1,
        table_title="Table 1.1: Coal Production",
    )
    base.update(kwargs)
    return NormalizedFact(**base)


def _upload(client, path: Path):
    with path.open("rb") as f:
        return client.post(
            "/api/documents/upload",
            files={"file": (path.name, f, "application/pdf")},
            data={"mine_name": "Lab"},
        )


def test_absolute_and_percentage_change():
    assert absolute_change(85.81, 88.58) == pytest.approx(-2.77)
    pct, undef = percentage_change(85.81, 88.58)
    assert not undef
    assert pct == pytest.approx((85.81 - 88.58) / 88.58 * 100)


def test_percentage_change_zero_denominator():
    pct, undef = percentage_change(5.0, 0.0)
    assert undef is True
    assert pct is None


def test_units_compatible():
    assert units_compatible("MT", "mt")
    assert not units_compatible("MT", "MU")


def test_parse_compare_two_years():
    p = parse_query("Compare Alpha Co production during March for FY24 and FY25.")
    assert p.comparison_mode == "compare"
    assert "March" in p.reporting_months
    assert "during" in p.measure_types
    assert any("2024" in x for x in p.periods) and any("2025" in x for x in p.periods)


def test_parse_change_intent():
    p = parse_query("What was the change in Alpha Co production between FY24 and FY25?")
    assert p.comparison_mode == "change"
    assert p.entity and "alpha" in p.entity.lower()


def test_parse_rank_intent():
    p = parse_query("Which year had higher Alpha Co production during March, FY24 or FY25?")
    assert p.comparison_mode == "rank"


def test_parse_multi_entity_compare():
    p = parse_query("Compare production of Echo Pit and Delta Pit during March.")
    assert p.comparison_mode == "compare"
    names = " ".join(p.entities).lower()
    assert "echo" in names and "delta" in names


def test_two_year_comparison_reasoning():
    plan = parse_query("Compare Alpha Co coal during March for FY24 and FY25.")
    facts = [
        _fact(fy="FY2024", value=88.58),
        _fact(fy="FY2025", value=85.81),
    ]
    result = reason_over_facts(plan, facts)
    assert result.status == "ok"
    assert result.calculation is not None
    assert result.calculation.absolute_change == pytest.approx(-2.77)
    assert result.calculation.percentage_change == pytest.approx(
        (85.81 - 88.58) / 88.58 * 100
    )
    text = format_multi_fact_answer(plan, result)
    assert "88.58" in text and "85.81" in text
    assert "page 1" in text


def test_entity_comparison_reasoning():
    plan = parse_query("Compare coal production of Echo Pit and Delta Pit during March.")
    facts = [
        _fact(entity="Echo Pit", fy="FY2025", value=2.40),
        _fact(entity="Delta Pit", fy="FY2025", value=1.40),
    ]
    result = reason_over_facts(plan, facts)
    assert result.status == "ok"
    assert result.higher_label == "Echo Pit"
    assert result.lower_label == "Delta Pit"


def test_missing_fy_insufficient():
    plan = parse_query("Compare Alpha Co coal during March for FY24 and FY25.")
    facts = [_fact(fy="FY2025", value=85.81)]  # FY24 missing
    result = reason_over_facts(plan, facts)
    assert result.status == "insufficient"


def test_conflicting_facts_not_merged():
    plan = parse_query("Compare Alpha Co coal during March for FY24 and FY25.")
    facts = [
        _fact(fy="FY2025", value=85.81, page=5),
        _fact(fy="FY2025", value=2.91, page=71, table_title="Other"),
        _fact(fy="FY2024", value=88.58, page=5),
    ]
    result = reason_over_facts(plan, facts)
    assert result.status == "conflict"
    text = format_multi_fact_answer(plan, result)
    assert "Human verification" in text
    assert "85.81" in text and "2.91" in text


def test_unit_mismatch():
    plan = parse_query("Compare Alpha Co coal during March for FY24 and FY25.")
    facts = [
        _fact(fy="FY2024", value=88.58, unit="MT"),
        _fact(fy="FY2025", value=85.81, unit="MU"),
    ]
    result = reason_over_facts(plan, facts)
    assert result.status == "unit_mismatch"


def test_different_months_not_interchangeable():
    plan = parse_query("Compare Alpha Co coal during March for FY25 and FY24.")
    facts = [
        _fact(fy="FY2025", period="December", value=50.0),
        _fact(fy="FY2024", period="December", value=40.0),
    ]
    result = reason_over_facts(plan, facts)
    assert result.status == "insufficient"


def test_different_metrics_not_mixed():
    plan = parse_query("Compare Alpha Co coal during March for FY24 and FY25.")
    facts = [
        _fact(fy="FY2025", metric="lignite", value=3.11),
        _fact(fy="FY2024", metric="lignite", value=3.05),
    ]
    result = reason_over_facts(plan, facts)
    assert result.status == "insufficient"


def test_cil_never_matches_nlcil_in_reasoning():
    plan = parse_query("Compare CIL coal during March for FY24 and FY25.")
    facts = [
        _fact(entity="NLCIL", fy="FY2025", value=2.91, metric="lignite"),
        _fact(entity="NLCIL", fy="FY2024", value=2.85, metric="lignite"),
    ]
    result = reason_over_facts(plan, facts)
    assert result.status == "insufficient"


def test_agreeing_duplicates_collapsed():
    facts = [
        _fact(fy="FY2025", value=85.81, page=5),
        _fact(fy="FY2025", value=85.81, page=56, table_title="All figures in MT"),
    ]
    unique, conflicts = resolve_unique_facts(facts)
    assert not conflicts
    assert len(unique) == 1


def test_e2e_two_year_compare(client, tmp_path, db_session):
    path = build_production_table_pdf(
        tmp_path / "compare.pdf",
        title="Table 1.1: Coal Production",
        month_label="Mar",
        entities=[
            ("Echo Pit", 2.50, 2.40, 2.30, 20.00, 19.00),
            ("Delta Pit", 1.50, 1.40, 1.30, 10.00, 9.00),
        ],
    )
    _upload(client, path)
    q = "Compare Echo Pit coal production during March for FY24 and FY25."
    out = ask_assistant(db_session, q)
    assert out.get("comparison_mode") == "compare"
    mf = out.get("multi_fact") or {}
    assert mf.get("status") == "ok"
    reply = out.get("reply") or ""
    assert "2.4" in reply or "2.40" in reply
    assert "2.3" in reply or "2.30" in reply
    calc = mf.get("calculation") or {}
    assert calc.get("absolute_change") == pytest.approx(0.1)


def test_e2e_entity_compare(client, tmp_path, db_session):
    path = build_production_table_pdf(
        tmp_path / "ent.pdf",
        title="Table 1.1: Coal Production",
        month_label="Mar",
        entities=[
            ("Echo Pit", 2.50, 2.40, 2.30, 20.00, 19.00),
            ("Delta Pit", 1.50, 1.40, 1.30, 10.00, 9.00),
        ],
    )
    _upload(client, path)
    q = "Compare production of Echo Pit and Delta Pit during March."
    out = ask_assistant(db_session, q)
    mf = out.get("multi_fact") or {}
    assert mf.get("status") == "ok", mf
    assert mf.get("higher_label") == "Echo Pit"


def test_single_fact_still_works(client, tmp_path, db_session):
    path = build_production_table_pdf(
        tmp_path / "single.pdf",
        title="Table 1.1: Coal Production",
        month_label="Mar",
        entities=[("Echo Pit", 2.50, 2.40, 2.30, 20.00, 19.00)],
    )
    _upload(client, path)
    q = "How much did Echo Pit produce coal during March FY25?"
    plan = parse_query(q)
    assert plan.comparison_mode is None
    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    assert hits
    assert any("Echo Pit" in h.text and "2.4" in h.text for h in hits)
