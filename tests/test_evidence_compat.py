"""Generic entity/metric/period evidence compatibility (no hard-coded answers)."""

from __future__ import annotations

from pathlib import Path

import fitz

from app.assistant.evidence_filter import evidence_compatible, text_matches_entity
from app.assistant.query_router import parse_query, resolve_route
from app.assistant.rag_retriever import retrieve_rag_evidence
from app.assistant.service import ask_assistant


def _upload(client, path: Path, name: str | None = None):
    with path.open("rb") as f:
        return client.post(
            "/api/documents/upload",
            files={"file": (name or path.name, f, "application/pdf")},
            data={"mine_name": "Lab Mine"},
        )


def _pdf_with_text(path: Path, text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), text, fontsize=10)
    doc.save(path)
    doc.close()
    return path


def test_parse_geography_coal_multi_year_shorthand():
    """Arbitrary state + coal + fy24/fy25 shorthand — no hard-coded geography list."""
    q = "how much did telangana produce coal in the fy25 and fy24?"
    plan = parse_query(q)
    assert plan.entity and "telangana" in plan.entity.lower()
    assert "coal" in (plan.metrics or []) or plan.metric == "coal"
    assert any("2024" in p for p in plan.periods)
    assert any("2025" in p for p in plan.periods)
    assert plan.prefers_numeric


def test_parse_unseen_state_and_company():
    p_state = parse_query("how much did andhra pradesh produce coal in fy24?")
    assert p_state.entity and "andhra" in p_state.entity.lower()
    assert "coal" in (p_state.metrics or []) or p_state.metric == "coal"
    assert any("2024" in p for p in p_state.periods)

    p_co = parse_query("What was NLC India lignite production in FY2023-24?")
    assert p_co.entity and "nlc" in p_co.entity.lower()
    assert "lignite" in (p_co.metrics or [])


def test_parse_mine_and_unseen_entity_metric():
    p = parse_query("What was Mine B's production in FY2024?")
    assert p.entity and "mine b" in p.entity.lower()

    p2 = parse_query("What was Basin West's overburden in FY2024?")
    assert p2.entity and "basin" in p2.entity.lower()
    assert "overburden" in (p2.metrics or []) or p2.metric == "overburden"


def test_evidence_compat_rejects_company_for_state_coal():
    plan = parse_query("how much did telangana produce coal in the fy25 and fy24?")
    nlc_lignite = (
        "NLC India Limited Production Performance for FY 2023-24. "
        "Lignite: actual 23.68 MT. Overburden removed. Power generation."
    )
    bad = evidence_compatible(plan, nlc_lignite, require_entity=True, require_metric=True)
    assert not bad.ok
    assert (
        "entity_mismatch" in bad.reasons
        or "lignite_not_coal" in bad.reasons
        or "metric_mismatch" in bad.reasons
    )

    good = evidence_compatible(
        plan,
        "Telangana coal production FY2024 was reported in the state mineral digest.",
        require_entity=True,
        require_metric=True,
        require_period=False,
    )
    assert good.ok


def test_evidence_compat_coal_vs_lignite():
    plan = parse_query("What was NLC India lignite production in FY2024?")
    ok = evidence_compatible(
        plan,
        "NLC India Limited lignite production FY2024 actual 23.68 MT",
        require_entity=True,
        require_metric=True,
    )
    assert ok.ok

    coal_plan = parse_query("how much coal did NLC India produce in FY2024?")
    lignite_only = "NLC India Limited lignite production FY2024 actual 23.68 MT"
    reject = evidence_compatible(
        coal_plan, lignite_only, require_entity=True, require_metric=True
    )
    assert not reject.ok


def test_evidence_compat_period_and_partial_year(client, tmp_path, db_session):
    """Only one of two requested years present → keep entity match; no substitution."""
    path = _pdf_with_text(
        tmp_path / "ridge.pdf",
        "Ridge Valley coal production in FY2024 reached 4.1 million tons. "
        "No FY2025 figure is published in this digest.",
    )
    up = _upload(client, path)
    doc_id = up.json()["id"]
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200

    q = "how much did Ridge Valley produce coal in the fy25 and fy24?"
    plan = parse_query(q)
    assert plan.entity and "ridge" in plan.entity.lower()
    assert any("2024" in p for p in plan.periods) and any("2025" in p for p in plan.periods)

    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    for h in hits:
        assert text_matches_entity(h.text, plan.entity)

    body = ask_assistant(db_session, q)
    rag_text = " ".join((h.get("evidence") or "") for h in body.get("rag_evidence") or [])
    sources_text = " ".join((s.get("snippet") or "") for s in body.get("sources") or [])
    blob = ((body.get("reply") or "") + rag_text + sources_text).lower()
    assert "nlc india" not in blob or "ridge" in blob
    if not body.get("rag_evidence") and not body.get("structured_evidence"):
        reply = (body.get("reply") or "").lower()
        assert "couldn't find" in reply or "verified evidence" in reply


def test_no_matching_evidence_refuses_substitution(client, tmp_path, db_session):
    """Unseen geography must not cite NLC lignite as supporting evidence."""
    path = _pdf_with_text(
        tmp_path / "nlc_blur.pdf",
        "NLC India Limited Production Performance for FY 2023-24. "
        "Lignite actual 12.64 million tons. Overburden and power generation.",
    )
    up = _upload(client, path)
    doc_id = up.json()["id"]
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200

    q = "how much did telangana produce coal in the fy25 and fy24?"
    plan = resolve_route(db_session, parse_query(q))
    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    assert all("telangana" in (h.text or "").lower() for h in hits)

    body = ask_assistant(db_session, q)
    reply = (body.get("reply") or "").lower()
    rag = body.get("rag_evidence") or []
    assert not rag or all("telangana" in (x.get("evidence") or "").lower() for x in rag)
    assert "12.64" not in reply
    if not rag:
        assert (
            "couldn't find" in reply
            or "could not find" in reply
            or "verified evidence" in reply
            or "verified information" in reply
            or "insufficient" in reply
        )


def test_compatible_company_metric_still_retrievable(client, tmp_path, db_session):
    """Matching entity+metric evidence (company + lignite) must still pass."""
    path = _pdf_with_text(
        tmp_path / "nlc_ok.pdf",
        "NLC India Limited Production Performance for FY 2023-24. "
        "Lignite production actual 23.68 MT.",
    )
    up = _upload(client, path)
    doc_id = up.json()["id"]
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200

    q = "What was NLC India lignite production in FY2023-24?"
    plan = parse_query(q)
    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    assert hits, "matching NLC lignite evidence should pass compatibility"
    assert any("lignite" in (h.text or "").lower() for h in hits)
    assert any("nlc" in (h.text or "").lower() for h in hits)
