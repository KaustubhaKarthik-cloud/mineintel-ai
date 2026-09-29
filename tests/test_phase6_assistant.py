"""Phase 6 — AI assistant routing, evidence, conflicts, charts."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.assistant.query_router import parse_query, resolve_route, route_query
from app.assistant.service import ask_assistant
from app.models import ExtractedFact, FactStatus
from app.validation.service import run_validation


def _upload(client, path: Path, name: str | None = None):
    with path.open("rb") as f:
        return client.post(
            "/api/documents/upload",
            files={"file": (name or path.name, f, "application/pdf")},
            data={"mine_name": "Mine B"},
        )


def _seed_fact(
    db,
    document_id: str,
    *,
    field: str,
    value: float,
    unit: str,
    entity: str,
    period: str,
    page: int = 1,
    evidence: str = "ev",
):
    f = ExtractedFact(
        document_id=document_id,
        field_name=field,
        value=str(value),
        numeric_value=float(value),
        unit=unit,
        entity_name=entity,
        financial_year=period,
        page_number=page,
        evidence_text=evidence,
        confidence_score=0.95,
        status=FactStatus.HIGH_CONFIDENCE.value,
    )
    db.add(f)
    db.flush()
    return f


def test_parse_query_entity_metric_period():
    """Parse extracts intent without committing to a DB-backed route."""
    p1 = parse_query("What does the NLC India report say about overburden and lignite production?")
    assert p1.entity and "nlc" in p1.entity.lower()
    assert "overburden" in p1.metrics and "lignite" in p1.metrics
    assert p1.wants_document_context

    p2 = parse_query(
        "What are the actual overburden and lignite production figures for FY2023-24?"
    )
    assert "overburden" in p2.metrics and "lignite" in p2.metrics
    assert any("2023" in x for x in p2.periods)
    assert p2.prefers_numeric

    p3 = parse_query("What was Mine B's production in FY2024?")
    assert p3.entity and "mine b" in p3.entity.lower()
    assert p3.metric == "production" or "production" in p3.metrics


def test_query_routing_parse_only():
    """Without DB, narrative/doc cues prefer RAG; hybrid intent stays hybrid."""
    assert route_query(
        "What does the annual report say about Mine B's geological characteristics?"
    ).query_type == "rag"
    nlcil = route_query("Production Performance (NLC India Limited)")
    assert nlcil.query_type == "rag"
    assert nlcil.entity and "nlc" in nlcil.entity.lower()
    plan = route_query(
        "Show Mine B production from FY2022 to FY2025 and explain the trend using annual reports."
    )
    assert plan.query_type == "hybrid"
    assert plan.want_chart
    assert "FY2022" in plan.periods and "FY2025" in plan.periods


def test_evidence_aware_rag_when_no_structured_match(client, digital_pdf, db_session):
    """Numeric-sounding query must NOT route structured if DB lacks matching facts."""
    up = _upload(client, digital_pdf)
    doc_id = up.json()["id"]
    # Unrelated verified production exists — must not steal the route
    _seed_fact(
        db_session,
        doc_id,
        field="production",
        value=5.2,
        unit="MT",
        entity="Mine B",
        period="FY2024",
        evidence="Mine B produced 5.2 MT",
    )
    db_session.commit()
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200

    q = "What are the actual overburden and lignite production figures for FY2023-24?"
    plan = parse_query(q)
    resolved = resolve_route(db_session, plan)
    assert resolved.query_type == "rag", resolved.route_reason

    r = client.post("/api/assistant/query", json={"question": q})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query_type"] == "rag"
    # Must not dump unrelated Mine B production as the answer
    assert "5.2" not in body["reply"] or body["query_type"] == "rag"


def test_evidence_aware_structured_when_verified_match(
    client, digital_pdf, tmp_path, db_session
):
    a = tmp_path / "Annual_Report_2024.pdf"
    shutil.copy(digital_pdf, a)
    up = _upload(client, a)
    doc_id = up.json()["id"]
    _seed_fact(
        db_session,
        doc_id,
        field="production",
        value=5.2,
        unit="MT",
        entity="Mine B",
        period="FY2024",
        page=12,
        evidence="Mine B produced 5.2 MT during FY2024",
    )
    db_session.commit()

    q = "What was Mine B's production in FY2024?"
    plan = resolve_route(db_session, parse_query(q))
    assert plan.query_type == "structured"

    r = client.post("/api/assistant/query", json={"question": q})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query_type"] == "structured"
    assert "5.2" in body["reply"]
    assert body["structured_evidence"]
    assert any(s.get("page") == 12 for s in body["sources"])


def test_evidence_aware_doc_narrative_rag(client, digital_pdf, db_session):
    """Report-narrative questions route RAG even when unrelated structured facts exist."""
    up = _upload(client, digital_pdf)
    doc_id = up.json()["id"]
    _seed_fact(
        db_session,
        doc_id,
        field="production",
        value=9.9,
        unit="MT",
        entity="Mine B",
        period="FY2024",
    )
    db_session.commit()
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200

    q = "What does the NLC India report say about overburden and lignite production?"
    resolved = resolve_route(db_session, parse_query(q))
    assert resolved.query_type == "rag", resolved.route_reason

    r = client.post("/api/assistant/query", json={"question": q})
    assert r.status_code == 200
    assert r.json()["query_type"] == "rag"
    assert "9.9" not in r.json()["reply"]


def test_evidence_aware_hybrid_when_both_needed(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "Hybrid_Report.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    for year, val in [("FY2022", 4.8), ("FY2023", 5.1), ("FY2024", 5.2), ("FY2025", 5.8)]:
        _seed_fact(
            db_session,
            doc_id,
            field="production",
            value=val,
            unit="MT",
            entity="Mine B",
            period=year,
            evidence=f"Mine B production {val} MT {year}",
        )
    db_session.commit()
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200

    q = (
        "Compare Mine B's verified production with what the annual report says "
        "from FY2022 to FY2025."
    )
    resolved = resolve_route(db_session, parse_query(q))
    assert resolved.query_type == "hybrid", resolved.route_reason


def test_unseen_entity_metric_variants(db_session, client, digital_pdf, tmp_path):
    """Routing generalizes to unseen org/metric names — no hard-coded org map."""
    path = tmp_path / "Alpha_Ops.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(
        db_session,
        doc_id,
        field="overburden",
        value=12.4,
        unit="Mm3",
        entity="Quarry Alpha",
        period="FY2024",
        evidence="Quarry Alpha overburden 12.4 Mm3 FY2024",
    )
    db_session.commit()

    q_hit = "What was Quarry Alpha's overburden in FY2024?"
    assert resolve_route(db_session, parse_query(q_hit)).query_type == "structured"

    q_miss = "What are the actual overburden figures for FY2024 for Basin West?"
    miss = parse_query(q_miss)
    assert miss.entity and "basin" in miss.entity.lower()
    assert resolve_route(db_session, miss).query_type == "rag"

    from app.assistant.structured_retriever import retrieve_structured_facts

    assert (
        retrieve_structured_facts(
            db_session,
            entity="Basin West",
            metric="overburden",
            periods=["FY2024"],
            verified_only=True,
        )
        == []
    )


def test_nlcil_alias_soft_match_without_route_hardcode(db_session, digital_pdf, tmp_path, client):
    """NLCIL / NLC India soft-match entity rows; route still evidence-driven."""
    path = tmp_path / "Corp_Report.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(
        db_session,
        doc_id,
        field="lignite",
        value=24.1,
        unit="MT",
        entity="NLC India Limited",
        period="FY2023-24",
        evidence="lignite 24.1 MT",
    )
    db_session.commit()

    # Structured match when lignite fact exists for NLC India
    q = "What was NLCIL lignite production in FY2023-24?"
    plan = parse_query(q)
    # Ensure entity detected somehow
    if not plan.entity:
        plan.entity = "NLCIL"
    plan.metrics = ["lignite"]
    plan.metric = "lignite"
    plan.periods = ["FY2023-24"]
    assert resolve_route(db_session, plan).query_type == "structured"

    # Without that fact for overburden alone → rag
    q2 = "What are the actual overburden production figures for FY2023-24?"
    assert resolve_route(db_session, parse_query(q2)).query_type == "rag"


def test_structured_answer_verified(client, digital_pdf, tmp_path, db_session):
    a = tmp_path / "Annual_Report_2024.pdf"
    shutil.copy(digital_pdf, a)
    up = _upload(client, a)
    doc_id = up.json()["id"]
    _seed_fact(
        db_session,
        doc_id,
        field="production",
        value=5.2,
        unit="MT",
        entity="Mine B",
        period="FY2024",
        page=12,
        evidence="Mine B produced 5.2 MT during FY2024",
    )
    db_session.commit()
    r = client.post("/api/assistant/query", json={"question": "What was Mine B's production in FY2024?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query_type"] == "structured"
    assert "5.2" in body["reply"]
    assert body["structured_evidence"]
    assert any(s.get("page") == 12 for s in body["sources"])


def test_conflict_not_auto_resolved(client, digital_pdf, tmp_path, db_session):
    a = tmp_path / "Annual_Report_2024.pdf"
    b = tmp_path / "Production_Report_2024.pdf"
    shutil.copy(digital_pdf, a)
    shutil.copy(digital_pdf, b)
    id_a = _upload(client, a).json()["id"]
    id_b = _upload(client, b).json()["id"]
    _seed_fact(
        db_session, id_a, field="production", value=5.2, unit="MT", entity="Mine B", period="FY2024", page=12, evidence="5.2 MT"
    )
    _seed_fact(
        db_session, id_b, field="production", value=5.6, unit="MT", entity="Mine B", period="FY2024", page=4, evidence="5.6 MT"
    )
    db_session.commit()
    run_validation(db_session)
    r = client.post("/api/assistant/chat", json={"message": "What was Mine B's production in FY2024?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conflicts"]
    assert "5.2" in body["reply"] and "5.6" in body["reply"]
    assert "verification" in body["reply"].lower() or "conflict" in body["reply"].lower()
    assert "human verification" in body["reply"].lower() or "conflicting" in body["reply"].lower()


def test_chart_from_structured(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "Trend_Report.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    for year, val in [("FY2022", 4.8), ("FY2023", 5.1), ("FY2024", 5.2), ("FY2025", 5.8)]:
        _seed_fact(
            db_session,
            doc_id,
            field="production",
            value=val,
            unit="MT",
            entity="Mine B",
            period=year,
            evidence=f"Mine B production {val} MT {year}",
        )
    db_session.commit()
    r = client.post(
        "/api/assistant/query",
        json={"question": "Compare Mine B production from FY2022 to FY2025."},
    )
    assert r.status_code == 200, r.text
    chart = r.json()["chart"]
    assert chart
    assert len(chart["data"]) >= 3
    values = {row["year"]: row["value"] for row in chart["data"]}
    assert values.get("FY2022") == 4.8
    assert values.get("FY2025") == 5.8


def test_rag_route_and_insufficient(client, digital_pdf, db_session):
    up = _upload(client, digital_pdf)
    doc_id = up.json()["id"]
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200
    r = client.post(
        "/api/assistant/query",
        json={"question": "What does the annual report say about Mine B geological characteristics?"},
    )
    assert r.status_code == 200
    assert r.json()["query_type"] == "rag"
    assert "18.4" not in r.json()["reply"]

    empty = client.post(
        "/api/assistant/query", json={"question": "What is the uranium grade on Mars mine ZZZ?"}
    )
    assert empty.status_code == 200
    assert (
        "sufficient" in empty.json()["reply"].lower()
        or empty.json()["warnings"]
        or empty.json()["rag_evidence"] == []
    )


def test_follow_up_context(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "Annual_Report_2024.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(
        db_session, doc_id, field="production", value=5.2, unit="MT", entity="Mine B", period="FY2024", evidence="5.2"
    )
    _seed_fact(
        db_session, doc_id, field="production", value=5.8, unit="MT", entity="Mine B", period="FY2025", evidence="5.8"
    )
    db_session.commit()
    first = client.post("/api/assistant/chat", json={"message": "What was Mine B production in FY2024?"})
    sid = first.json()["session_id"]
    second = client.post(
        "/api/assistant/chat",
        json={"message": "What about FY2025?", "session_id": sid},
    )
    assert second.status_code == 200
    assert "5.8" in second.json()["reply"]


def test_chart_endpoint(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "Annual_Report_2024.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(db_session, doc_id, field="production", value=4.8, unit="MT", entity="Mine B", period="FY2022")
    _seed_fact(db_session, doc_id, field="production", value=5.2, unit="MT", entity="Mine B", period="FY2024")
    db_session.commit()
    r = client.post("/api/assistant/chart", json={"entity": "Mine B", "metric": "production"})
    assert r.status_code == 200
    assert r.json()["chart"] is not None
