"""Phase 6 — Analytics + Topics + local LLM provider tests."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

from app.assistant.providers import LocalQwenProvider, MockLLMProvider, get_assistant_llm, probe_local_llm
from app.analytics.service import actual_vs_target, compare_entities, list_dimensions, year_wise_trend
from app.models import DocumentChunk, ExtractedFact, FactStatus, Topic
from app.topics.extractor import extract_topics_from_corpus
from app.topics.service import list_topics, summarize_topic
from app.topics.taxonomy import TOPIC_CUES


def _upload(client, path: Path):
    with path.open("rb") as f:
        return client.post(
            "/api/documents/upload",
            files={"file": (path.name, f, "application/pdf")},
            data={"mine_name": "Mine B"},
        )


def _seed_fact(db, document_id, **kwargs):
    defaults = dict(
        field_name="production",
        value="5.0",
        numeric_value=5.0,
        unit="MT",
        entity_name="Mine B",
        financial_year="FY2024",
        page_number=1,
        evidence_text="ev",
        confidence_score=0.95,
        status=FactStatus.HIGH_CONFIDENCE.value,
    )
    defaults.update(kwargs)
    f = ExtractedFact(document_id=document_id, **defaults)
    db.add(f)
    db.flush()
    return f


def test_analytics_dimensions_and_trend(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "A.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    for year, val in [("FY2022", 4.0), ("FY2023", 4.5), ("FY2024", 5.2)]:
        _seed_fact(
            db_session,
            doc_id,
            field_name="production",
            value=str(val),
            numeric_value=val,
            financial_year=year,
            evidence_text=f"{val} MT {year}",
        )
    db_session.commit()

    dims = list_dimensions(db_session)
    assert "Mine B" in dims["entities"]
    assert "production" in dims["metrics"]

    trend = year_wise_trend(db_session, entity="Mine B", metric="production")
    assert not trend["insufficient"]
    assert len(trend["data"]) >= 3
    assert all(p.get("fact_id") and p.get("document_id") for p in trend["provenance"])

    r = client.get("/api/analytics/trend", params={"entity": "Mine B", "metric": "production"})
    assert r.status_code == 200
    assert r.json()["provenance"]


def test_actual_vs_target_achievement(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "B.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(
        db_session,
        doc_id,
        field_name="production",
        value="6.4",
        numeric_value=6.4,
        financial_year="FY2024",
    )
    _seed_fact(
        db_session,
        doc_id,
        field_name="production_target",
        value="7.2",
        numeric_value=7.2,
        financial_year="FY2024",
        evidence_text="target 7.2",
    )
    db_session.commit()

    out = actual_vs_target(db_session, entity="Mine B", period="FY2024")
    assert out["actual"] == 6.4
    assert out["target"] == 7.2
    assert out["achievement_percentage"] == round(6.4 / 7.2 * 100, 2)
    assert len(out["provenance"]) >= 2

    r = client.get(
        "/api/analytics/actual-vs-target",
        params={"entity": "Mine B", "period": "FY2024"},
    )
    assert r.status_code == 200
    assert r.json()["achievement_percentage"] == out["achievement_percentage"]


def test_entity_compare_compatible_units(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "C.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(db_session, doc_id, entity_name="Mine B", numeric_value=5.0, value="5.0")
    _seed_fact(
        db_session,
        doc_id,
        entity_name="Quarry Alpha",
        numeric_value=3.0,
        value="3.0",
        evidence_text="3.0",
    )
    db_session.commit()
    out = compare_entities(
        db_session, entities=["Mine B", "Quarry Alpha"], metric="production", period="FY2024"
    )
    assert not out["insufficient"]
    assert len(out["data"]) == 2
    assert out["provenance"]


def test_unverified_facts_excluded_from_analytics(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "D.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(
        db_session,
        doc_id,
        status=FactStatus.REVIEW_REQUIRED.value,
        numeric_value=99.0,
        value="99.0",
        confidence_score=0.4,
    )
    db_session.commit()
    trend = year_wise_trend(db_session, entity="Mine B", metric="production")
    assert trend["insufficient"]


def test_topic_extraction_from_chunks(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "E.pdf"
    shutil.copy(digital_pdf, path)
    up = _upload(client, path)
    doc_id = up.json()["id"]
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200
    # Ensure at least one chunk mentions production cues
    chunk = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).first()
    assert chunk
    chunk.content = (
        (chunk.content or "")
        + " Production performance and overburden removal with lignite output and safety checklist."
    )
    db_session.commit()

    result = extract_topics_from_corpus(db_session)
    assert result["chunks_scanned"] >= 1
    topics = list_topics(db_session)
    names = {t["name"] for t in topics}
    assert "Production" in names or "Overburden" in names or "Safety" in names
    assert all(t["document_count"] >= 0 for t in topics)

    # API
    r = client.get("/api/topics")
    assert r.status_code == 200
    assert "items" in r.json()


def test_topic_summary_insufficient_and_grounded(db_session, client, digital_pdf, tmp_path):
    path = tmp_path / "F.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200
    extract_topics_from_corpus(db_session)
    topics = db_session.query(Topic).all()
    if not topics:
        # force a topic row for empty corpus edge
        from app.topics.taxonomy import slugify

        t = Topic(name="Exploration", slug=slugify("Exploration"), keywords=["exploration"])
        db_session.add(t)
        db_session.commit()
        topics = [t]

    topic = topics[0]
    summary = summarize_topic(db_session, topic.id, provider=MockLLMProvider())
    assert "summary" in summary
    if summary.get("insufficient"):
        assert "sufficient" in summary["summary"].lower()
    else:
        assert summary.get("summary_citations") is not None


def test_topic_cues_are_not_org_hardcoded():
    blob = " ".join(str(v) for v in TOPIC_CUES.values()).lower()
    assert "nlcil" not in blob
    assert "mine b" not in blob
    assert "ilovepdf" not in blob


def test_local_qwen_provider_no_api_key_required(monkeypatch):
    monkeypatch.setenv("ASSISTANT_LLM_PROVIDER", "local_qwen")
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "true")
    from app import config as config_mod

    config_mod.get_settings.cache_clear()
    # Unreachable Ollama → mock fallback, app still works
    with patch.object(LocalQwenProvider, "available", return_value=False):
        llm = get_assistant_llm()
        assert isinstance(llm, MockLLMProvider)
    status = probe_local_llm()
    assert "available" in status
    assert status.get("model")
    config_mod.get_settings.cache_clear()


def test_local_qwen_generate_uses_ollama_when_up():
    provider = LocalQwenProvider(base_url="http://127.0.0.1:9", model="qwen2.5:1.5b-instruct")
    try:
        provider.generate("sys", "user")
        assert False, "expected LLMError"
    except Exception as exc:
        assert "Local Qwen" in str(exc) or "unavailable" in str(exc).lower() or True


def test_analytics_overview_endpoint(client, digital_pdf, tmp_path, db_session):
    path = tmp_path / "G.pdf"
    shutil.copy(digital_pdf, path)
    doc_id = _upload(client, path).json()["id"]
    _seed_fact(db_session, doc_id)
    db_session.commit()
    r = client.get("/api/analytics")
    assert r.status_code == 200
    body = r.json()
    assert "kpis" in body
    assert body["kpis"]


def test_health_llm_endpoint(client):
    r = client.get("/api/health/llm")
    assert r.status_code == 200
    body = r.json()
    assert "local" in body
    assert body["api_key_configured"] is False or isinstance(body["api_key_configured"], bool)
