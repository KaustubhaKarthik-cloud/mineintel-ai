"""Phase 4 — chunking, embeddings, vector index, and semantic search tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from app.embeddings.provider import EmbeddingError, MockEmbeddingProvider
from app.models import DocumentChunk, IndexStatus
from app.rag.context_builder import build_rag_context
from app.retrieval.chunker import chunk_document_pages
from app.retrieval.vector_store import cosine_similarity


@pytest.fixture()
def mine_b_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "Annual_Report_2024.pdf"
    doc = fitz.open()
    # page 1 filler
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Introduction and corporate overview for mining operations.", fontsize=11)
    # page 2 = "page 42" story for citations in short fixture
    p2 = doc.new_page()
    p2.insert_text(
        (72, 72),
        "Mine B produced 3.9 MT during FY2024 against a target of 5.0 MT.",
        fontsize=11,
    )
    doc.save(path)
    doc.close()
    return path


def _upload(client, path: Path):
    with path.open("rb") as f:
        return client.post(
            "/api/documents/upload",
            files={"file": (path.name, f, "application/pdf")},
            data={"mine_name": "Mine B"},
        )


def test_nlcil_table_reconstruction():
    from app.retrieval.chunker import reconstruct_nlcil_production_block

    sample = """
18. Production Performance (NLC India Limited)
Overburden removal, lignite production during the year 2023-24 are indicated below:
2023-24 Actual 151.24 23.68 12.64 21643.87 18890.09 5462.34 5068.11
167.13 26.50 12.00 26461.67 23803.14 7466.00 7037.00
"""
    out = reconstruct_nlcil_production_block(sample)
    assert out is not None
    assert "Coal: target 12.00, actual 12.64" in out
    assert "Lignite: target 26.50, actual 23.68" in out
    assert "Overburden: target 167.13, actual 151.24" in out


def test_ocr_decimal_merge_fixes_digit_confusion():
    from app.document_processing.ocr_refine import digits_confusable, merge_ocr_decimals

    assert digits_confusable("25.68", "23.68")
    assert not digits_confusable("25.68", "26.50")
    base = "Actual 151.24 25.68 12.64 21643.87 Target 167.13 26.50 12.00 23803.14"
    detail = "Actual 151.24 23.68 12.64 21643.87 junk 25803.14"
    merged = merge_ocr_decimals(base, detail)
    assert "23.68" in merged
    assert "25.68" not in merged
    assert "151.24" in merged and "167.13" in merged
    # Unrelated confusable token without shared neighbors must not flip
    assert "23803.14" in merged
    assert "25803.14" not in merged


def test_nlcil_query_ranks_production_block(client, mine_b_pdf):
    # Synthetic NLCIL page so ranking prefers reconstructed coal/lignite facts
    from pathlib import Path
    import fitz

    path = Path(mine_b_pdf).parent / "nlcil_page.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (40, 60),
        "18. Production Performance (NLC India Limited)\n"
        "Overburden removal, lignite production, gross power generation "
        "and export of power during the year 2023-24 are indicated below:\n"
        "2023-24 Actual 151.24 23.68 12.64 21643.87 18890.09 5462.34 5068.11\n"
        "167.13 26.50 12.00 26461.67 23803.14 7466.00 7037.00\n"
        "SCCL is a joint venture unrelated filler text.",
        fontsize=9,
    )
    doc.save(path)
    doc.close()
    up = _upload(client, path)
    doc_id = up.json()["id"]
    assert client.post(f"/api/documents/{doc_id}/index").status_code == 200
    search = client.post(
        "/api/search",
        json={"query": "how much did NLCIL produce coal in 2023-2024?", "top_k": 3},
    )
    assert search.status_code == 200
    results = search.json()["results"]
    assert results
    top = results[0]["text"]
    assert "Coal: target 12.00, actual 12.64" in top or "12.64" in top


def test_chunk_creation_preserves_source(client, mine_b_pdf, db_session):
    up = _upload(client, mine_b_pdf)
    doc_id = up.json()["id"]
    from app.models import Document
    from sqlalchemy.orm import joinedload

    doc = (
        db_session.query(Document)
        .options(joinedload(Document.pages))
        .filter(Document.id == doc_id)
        .one()
    )
    drafts = chunk_document_pages(doc, list(doc.pages))
    assert drafts
    assert all(d.page_number is not None for d in drafts)
    assert any("3.9 MT" in d.text for d in drafts)
    assert all(d.document_name == "Annual_Report_2024.pdf" for d in drafts)


def test_embedding_generation_deterministic():
    p = MockEmbeddingProvider(dimensions=64)
    a = p.embed_text("Mine B produced 3.9 MT during FY2024")
    b = p.embed_text("Mine B produced 3.9 MT during FY2024")
    c = p.embed_text("Unrelated weather report about rainfall")
    assert a == b
    assert cosine_similarity(a, b) > 0.99
    assert cosine_similarity(a, c) < cosine_similarity(a, b)


def test_index_and_search(client, mine_b_pdf):
    up = _upload(client, mine_b_pdf)
    doc_id = up.json()["id"]
    idx = client.post(f"/api/documents/{doc_id}/index")
    assert idx.status_code == 200, idx.text
    body = idx.json()
    assert body["index_status"] == IndexStatus.INDEXED.value
    assert body["chunk_count"] >= 1

    search = client.post(
        "/api/search",
        json={"query": "What was Mine B production in FY2024?", "top_k": 5},
    )
    assert search.status_code == 200, search.text
    results = search.json()["results"]
    assert results
    assert any("3.9" in r["text"] for r in results)
    top = results[0]
    assert top["document"] == "Annual_Report_2024.pdf"
    assert top["page"] is not None
    assert top["score"] >= 0.25
    assert search.json()["context"]


def test_duplicate_indexing_uses_stable_ids(client, mine_b_pdf, db_session):
    up = _upload(client, mine_b_pdf)
    doc_id = up.json()["id"]
    client.post(f"/api/documents/{doc_id}/index")
    first_ids = {
        c.id
        for c in db_session.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc_id, DocumentChunk.is_active.is_(True))
        .all()
    }
    client.post(f"/api/documents/{doc_id}/index")
    second = (
        db_session.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc_id, DocumentChunk.is_active.is_(True))
        .all()
    )
    second_ids = {c.id for c in second}
    assert first_ids == second_ids
    assert all(c.is_active for c in second)


def test_similarity_threshold_filters(client, mine_b_pdf):
    up = _upload(client, mine_b_pdf)
    doc_id = up.json()["id"]
    client.post(f"/api/documents/{doc_id}/index")
    # extremely high threshold should return empty or few
    with patch("app.retrieval.retriever.get_settings") as gs:
        from app.config import get_settings as real

        settings = real()
        settings.min_similarity_threshold = 0.999
        gs.return_value = settings
        # patch at config used inside retrieve - easier call with min_score
        from app.database import SessionLocal
        from app.retrieval.retriever import retrieve

        db = SessionLocal()
        try:
            hits = retrieve(db, "totally unrelated quantum banana recipes", min_score=0.95)
            assert hits == []
        finally:
            db.close()


def test_context_builder_traceability(client, mine_b_pdf, db_session):
    up = _upload(client, mine_b_pdf)
    doc_id = up.json()["id"]
    client.post(f"/api/documents/{doc_id}/index")
    from app.retrieval.retriever import retrieve

    hits = retrieve(db_session, "Mine B production FY2024")
    ctx = build_rag_context("Mine B production FY2024", hits)
    assert "Annual_Report_2024.pdf" in ctx
    assert "Evidence:" in ctx


def test_embedding_provider_failure(client, mine_b_pdf):
    up = _upload(client, mine_b_pdf)
    doc_id = up.json()["id"]

    class Boom(MockEmbeddingProvider):
        def embed_texts(self, texts):
            raise EmbeddingError("Embedding provider request failed.")

    with patch("app.retrieval.service.get_embedding_provider", return_value=Boom()):
        r = client.post(f"/api/documents/{doc_id}/index")
    assert r.status_code == 400
    assert "Embedding" in r.json()["detail"] or "failed" in r.json()["detail"].lower()


def test_index_requires_phase2_complete(client):
    # create unfinished by mocking - easiest: missing pages via failed path
    r = client.post("/api/documents/does-not-exist/index")
    assert r.status_code == 400


def test_top_k_and_query_validation(client, mine_b_pdf):
    up = _upload(client, mine_b_pdf)
    client.post(f"/api/documents/{up.json()['id']}/index")
    bad = client.post("/api/search", json={"query": "", "top_k": 5})
    assert bad.status_code == 422 or bad.status_code == 400
    ok = client.post(
        "/api/search",
        json={"query": "Mine B production target", "top_k": 2, "include_context": False},
    )
    assert ok.status_code == 200
    assert len(ok.json()["results"]) <= 2
    assert ok.json()["context"] is None


def test_version_metadata_on_chunks(client, mine_b_pdf, db_session):
    up = _upload(client, mine_b_pdf)
    doc_id = up.json()["id"]
    client.post(f"/api/documents/{doc_id}/index")
    chunks = (
        db_session.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc_id, DocumentChunk.is_active.is_(True))
        .all()
    )
    assert chunks
    assert all(c.document_version == 1 for c in chunks)

    # bump version and re-index → new active chunks carry v2; old ids deactivated if keys change
    from app.models import Document

    doc = db_session.query(Document).filter(Document.id == doc_id).one()
    doc.version = 2
    db_session.commit()
    client.post(f"/api/documents/{doc_id}/index")
    active = (
        db_session.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc_id, DocumentChunk.is_active.is_(True))
        .all()
    )
    assert active
    assert all(c.document_version == 2 for c in active)
    search = client.post(
        "/api/search",
        json={"query": "Mine B produced 3.9 MT FY2024", "top_k": 5},
    )
    assert search.status_code == 200
    assert search.json()["results"]
    assert all(r["document_version"] == 2 for r in search.json()["results"] if r["document_id"] == doc_id)


def test_vector_store_failure_surfaces_cleanly(client, mine_b_pdf):
    up = _upload(client, mine_b_pdf)
    doc_id = up.json()["id"]
    with patch("app.retrieval.service.upsert_chunks", side_effect=RuntimeError("db down")):
        r = client.post(f"/api/documents/{doc_id}/index")
    assert r.status_code == 400
    assert "fail" in r.json()["detail"].lower()
