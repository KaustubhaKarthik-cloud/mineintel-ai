"""Regression: multi-entity compare + slash entity names (generic, no org hard-codes)."""

from __future__ import annotations

from app.assistant.query_router import parse_query


def test_compare_ecl_and_cil_case_insensitive():
    plan = parse_query("Compare ECL and CIL production during March")
    ents = [e.upper() for e in (plan.entities or [])]
    assert "ECL" in ents
    assert "CIL" in ents
    assert len(plan.entities) >= 2
    assert "March" in (plan.reporting_months or [])
    assert "during" in (plan.measure_types or [])


def test_compare_lowercase_compare_keyword():
    plan = parse_query("compare bccL and ccl coal during March")
    ents = {e.upper() for e in (plan.entities or [])}
    assert "BCCL" in ents
    assert "CCL" in ents


def test_captive_slash_others_what_was_form():
    plan = parse_query("What was Captive/Others coal production during March FY25?")
    assert plan.entity
    assert "captive" in plan.entity.lower()
    assert "/" in plan.entity or "others" in plan.entity.lower()


def test_compare_captive_slash_and_cil():
    plan = parse_query("Compare Captive/Others and CIL coal during March")
    joined = " ".join(plan.entities or []).lower()
    assert "cil" in joined
    assert "captive" in joined
    assert any("/" in e or "others" in e.lower() for e in (plan.entities or []))
