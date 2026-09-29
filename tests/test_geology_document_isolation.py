"""Document isolation / session-context for geological queries (no hard-coded answers)."""

from __future__ import annotations

from app.assistant.document_resolver import (
    DocumentScope,
    dedupe_evidence_by_page_content,
    filename_key,
    filter_hits_by_scope,
    is_cross_document_query,
    is_deictic_document_query,
    prefer_canonical_ids,
    resolve_document_scope,
)
from app.assistant.query_router import parse_query
from app.assistant.structured_retriever import StructuredFactHit
from app.models import Document, IndexStatus


def test_deictic_this_exploration_report():
    assert is_deictic_document_query(
        "What coal seams are reported in this exploration report?"
    )
    assert is_deictic_document_query("Which boreholes are mentioned in this document?")
    assert not is_deictic_document_query(
        "What coal seams are reported in North Parbelia?"
    )


def test_cross_document_compare_detected():
    assert is_cross_document_query(
        "Compare the coal seams in North Parbelia and West Sheetaldhara."
    )
    assert not is_cross_document_query(
        "What coal seams are reported in this exploration report?"
    )


def test_deictic_clears_stale_prior_entity():
    plan = parse_query(
        "What coal seams are reported in this exploration report?",
        prior_entity="West of Sheetaldhara",
    )
    assert plan.is_geological
    assert plan.deictic_document is True
    assert plan.entity is None


def test_filename_key_groups_duplicates():
    assert filename_key("North_Parbelia_G3.pdf") == filename_key("north_parbelia_g3.PDF")
    assert filename_key("West_of_Sheetaldhara.pdf") != filename_key("North_Parbelia_G3.pdf")


def test_filter_hits_by_scope_rejects_foreign_docs():
    hits = [
        StructuredFactHit(
            entity="a",
            metric="seam",
            period=None,
            value="R4",
            numeric_value=None,
            unit=None,
            status="high_confidence",
            document_id="doc-a",
            document_name="ReportA.pdf",
            document_version=1,
            page=11,
            sheet_name=None,
            evidence_text="seam",
            fact_id="1",
            confidence=0.9,
        ),
        StructuredFactHit(
            entity="b",
            metric="seam",
            period=None,
            value="Seam IV",
            numeric_value=None,
            unit=None,
            status="high_confidence",
            document_id="doc-b",
            document_name="ReportB.pdf",
            document_version=1,
            page=81,
            sheet_name=None,
            evidence_text="seam",
            fact_id="2",
            confidence=0.9,
        ),
    ]
    kept, rejected = filter_hits_by_scope(hits, ["doc-a"])
    assert len(kept) == 1
    assert kept[0].document_id == "doc-a"
    assert "ReportB.pdf" in rejected


def test_dedupe_evidence_collapses_same_page_copies():
    hits = [
        StructuredFactHit(
            entity="a",
            metric="seam",
            period=None,
            value="R4",
            numeric_value=None,
            unit=None,
            status="high_confidence",
            document_id="id-1",
            document_name="Same_Report.pdf",
            document_version=1,
            page=11,
            sheet_name=None,
            evidence_text="There are 2 seams found in block",
            fact_id="1",
            confidence=0.9,
        ),
        StructuredFactHit(
            entity="a",
            metric="seam",
            period=None,
            value="R4",
            numeric_value=None,
            unit=None,
            status="high_confidence",
            document_id="id-2",
            document_name="Same_Report.pdf",
            document_version=2,
            page=11,
            sheet_name=None,
            evidence_text="There are 2 seams found in block",
            fact_id="2",
            confidence=0.9,
        ),
    ]
    out = dedupe_evidence_by_page_content(hits)
    assert len(out) == 1


def test_resolve_scope_current_document(db_session):
    """Current document wins for this-report queries (generic fixtures)."""
    a = Document(
        id="scope-doc-a",
        filename="a.pdf",
        original_filename="Alpha_Block_Report.pdf",
        file_path="/tmp/a.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    b = Document(
        id="scope-doc-b",
        filename="b.pdf",
        original_filename="Beta_Block_Report.pdf",
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
        question="What coal seams are reported in this exploration report?",
        entity=None,
        current_document_id="scope-doc-a",
        is_geological=True,
    )
    assert scope.mode == "single_document"
    assert scope.allowed_ids == ["scope-doc-a"]
    assert "scope-doc-b" not in scope.allowed_ids


def test_resolve_scope_switch_documents(db_session):
    a = Document(
        id="sw-a",
        filename="swa.pdf",
        original_filename="Alpha_Switch.pdf",
        file_path="/tmp/swa.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    b = Document(
        id="sw-b",
        filename="swb.pdf",
        original_filename="Beta_Switch.pdf",
        file_path="/tmp/swb.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db_session.add_all([a, b])
    db_session.commit()

    q = "What coal seams are reported in this exploration report?"
    s1 = resolve_document_scope(
        db_session, question=q, entity=None, current_document_id="sw-a", is_geological=True
    )
    s2 = resolve_document_scope(
        db_session, question=q, entity=None, current_document_id="sw-b", is_geological=True
    )
    assert s1.allowed_ids != s2.allowed_ids
    assert "sw-a" in s1.allowed_ids and "sw-b" not in s1.allowed_ids
    assert "sw-b" in s2.allowed_ids and "sw-a" not in s2.allowed_ids
    assert s1.allowed_ids == ["sw-a"]
    assert s2.allowed_ids == ["sw-b"]


def test_resolve_scope_cross_document(db_session):
    a = Document(
        id="cx-a",
        filename="cxa.pdf",
        original_filename="North_Sample_Block.pdf",
        file_path="/tmp/cxa.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    b = Document(
        id="cx-b",
        filename="cxb.pdf",
        original_filename="West_Sample_Block.pdf",
        file_path="/tmp/cxb.pdf",
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
        question="Compare the coal seams in North Sample and West Sample.",
        entity="North Sample",
        entities=["North Sample", "West Sample"],
        current_document_id="cx-a",
        is_geological=True,
    )
    assert scope.mode == "cross_document_comparison"
    assert "cx-a" in scope.allowed_ids
    assert "cx-b" in scope.allowed_ids


def test_deictic_without_current_document_does_not_unscope(db_session):
    """'this report' with no selection must not search every geological PDF."""
    a = Document(
        id="dei-a",
        filename="a.pdf",
        original_filename="Alpha_Only.pdf",
        file_path="/tmp/a.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    b = Document(
        id="dei-b",
        filename="b.pdf",
        original_filename="Beta_Only.pdf",
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
        question="What coal seams are reported in this report?",
        entity=None,
        current_document_id=None,
        is_geological=True,
    )
    assert scope.mode == "single_document"
    assert scope.allowed_ids == []
    assert scope.reason == "deictic_missing_current_document"


def test_final_evidence_ids_subset_of_selected(db_session, monkeypatch):
    """API final evidence document_ids ⊆ {current_document_id} for deictic geo asks."""
    from app.assistant.service import ask_assistant, _SESSIONS
    from app.assistant.rag_retriever import RagHit

    a = Document(
        id="fin-a",
        filename="fina.pdf",
        original_filename="Final_Alpha.pdf",
        file_path="/tmp/fina.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    b = Document(
        id="fin-b",
        filename="finb.pdf",
        original_filename="Final_Beta.pdf",
        file_path="/tmp/finb.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db_session.add_all([a, b])
    db_session.commit()

    hit_a = StructuredFactHit(
        entity="Seam A",
        metric="seam",
        period=None,
        value="Seam A",
        numeric_value=None,
        unit=None,
        status="high_confidence",
        document_id="fin-a",
        document_name="Final_Alpha.pdf",
        document_version=1,
        page=1,
        sheet_name=None,
        evidence_text="seam A",
        fact_id="fa",
        confidence=0.9,
        seam_name="Seam A",
    )
    hit_b = StructuredFactHit(
        entity="Seam B",
        metric="seam",
        period=None,
        value="Seam B",
        numeric_value=None,
        unit=None,
        status="high_confidence",
        document_id="fin-b",
        document_name="Final_Beta.pdf",
        document_version=1,
        page=1,
        sheet_name=None,
        evidence_text="seam B",
        fact_id="fb",
        confidence=0.9,
        seam_name="Seam B",
    )

    def fake_geo(db, plan, **kwargs):
        ids = kwargs.get("document_ids")
        if ids is not None:
            return [h for h in (hit_a, hit_b) if h.document_id in ids]
        return [hit_a, hit_b]

    def fake_rag(db, q, **kwargs):
        ids = kwargs.get("document_ids")
        hits = [
            RagHit(
                text="seam evidence",
                score=0.9,
                document_id="fin-a",
                document_name="Final_Alpha.pdf",
                page=1,
                sheet_name=None,
                source_location=None,
                chunk_id="ca",
                content_type="document_evidence",
                document_version=1,
                compat_score=1.0,
                compat_reasons=[],
            ),
            RagHit(
                text="other seam",
                score=0.9,
                document_id="fin-b",
                document_name="Final_Beta.pdf",
                page=1,
                sheet_name=None,
                source_location=None,
                chunk_id="cb",
                content_type="document_evidence",
                document_version=1,
                compat_score=1.0,
                compat_reasons=[],
            ),
        ]
        if ids is not None:
            return [h for h in hits if h.document_id in ids]
        return hits

    monkeypatch.setattr(
        "app.assistant.geological_retriever.retrieve_geological_facts", fake_geo
    )
    monkeypatch.setattr("app.assistant.rag_retriever.retrieve_rag_evidence", fake_rag)
    monkeypatch.setattr(
        "app.assistant.service.generate_answer",
        lambda pack, provider=None: "scoped answer",
    )

    _SESSIONS.clear()
    r = ask_assistant(
        db_session,
        "What coal seams are reported in this report?",
        session_id="fin-test",
        document_id="fin-a",
    )
    ids = set()
    for e in (r.get("structured_evidence") or []) + (r.get("rag_evidence") or []):
        did = e.get("document_id")
        if did:
            ids.add(did)
    for s in r.get("sources") or []:
        if s.get("document_id"):
            ids.add(s["document_id"])
    assert ids <= {"fin-a"}
    assert r.get("document_scope_mode") == "single_document"
    names = {
        *(e.get("document_name") or e.get("document") or e.get("source") for e in (r.get("structured_evidence") or []) + (r.get("rag_evidence") or [])),
        *(s.get("document_name") for s in (r.get("sources") or [])),
    }
    assert "Final_Beta.pdf" not in names


def test_prefer_canonical_ids_picks_newest_duplicate(db_session):
    from datetime import datetime, timedelta

    older = Document(
        id="dup-old",
        filename="dup1.pdf",
        original_filename="Dup_Report.pdf",
        file_path="/tmp/dup1.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
        created_at=datetime.utcnow() - timedelta(days=2),
    )
    newer = Document(
        id="dup-new",
        filename="dup2.pdf",
        original_filename="Dup_Report.pdf",
        file_path="/tmp/dup2.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
        created_at=datetime.utcnow(),
    )
    db_session.add_all([older, newer])
    db_session.commit()
    canon = prefer_canonical_ids(db_session, ["dup-old", "dup-new"])
    assert canon == ["dup-new"]


def test_ask_assistant_scopes_to_current_document(db_session, monkeypatch):
    """End-to-end: current document_id isolates structured+RAG from other reports."""
    from app.assistant import service as svc
    from app.assistant.rag_retriever import RagHit

    a = Document(
        id="iso-a",
        filename="iso_a.pdf",
        original_filename="Isolation_Alpha.pdf",
        file_path="/tmp/iso_a.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    b = Document(
        id="iso-b",
        filename="iso_b.pdf",
        original_filename="Isolation_Beta.pdf",
        file_path="/tmp/iso_b.pdf",
        file_type="pdf",
        file_size=10,
        status="completed",
        index_status=IndexStatus.INDEXED.value,
        version=1,
    )
    db_session.add_all([a, b])
    db_session.commit()

    hit_a = StructuredFactHit(
        entity="Seam A",
        metric="seam",
        period=None,
        value="Seam A",
        numeric_value=None,
        unit=None,
        status="high_confidence",
        document_id="iso-a",
        document_name="Isolation_Alpha.pdf",
        document_version=1,
        page=5,
        sheet_name=None,
        evidence_text="Seam A identified",
        fact_id="fa",
        confidence=0.9,
        seam_name="Seam A",
    )
    hit_b = StructuredFactHit(
        entity="Seam B",
        metric="seam",
        period=None,
        value="Seam B",
        numeric_value=None,
        unit=None,
        status="high_confidence",
        document_id="iso-b",
        document_name="Isolation_Beta.pdf",
        document_version=1,
        page=9,
        sheet_name=None,
        evidence_text="Seam B identified",
        fact_id="fb",
        confidence=0.9,
        seam_name="Seam B",
    )

    def fake_geo(db, plan, **kwargs):
        ids = kwargs.get("document_ids")
        if ids is not None:
            return [h for h in (hit_a, hit_b) if h.document_id in ids]
        return [hit_a, hit_b]

    def fake_rag(db, query, **kwargs):
        ids = kwargs.get("document_ids")
        if ids is None and kwargs.get("document_id"):
            ids = [kwargs["document_id"]]
        hits = [
            RagHit(
                chunk_id="c1",
                document_id="iso-a",
                document_name="Isolation_Alpha.pdf",
                document_version=1,
                page=5,
                sheet_name=None,
                source_location="page:5",
                text="Seam A in alpha",
                score=0.9,
                content_type="text",
            ),
            RagHit(
                chunk_id="c2",
                document_id="iso-b",
                document_name="Isolation_Beta.pdf",
                document_version=1,
                page=9,
                sheet_name=None,
                source_location="page:9",
                text="Seam B in beta",
                score=0.9,
                content_type="text",
            ),
        ]
        if ids is not None:
            return [h for h in hits if h.document_id in ids]
        return hits

    monkeypatch.setattr(
        "app.assistant.geological_retriever.retrieve_geological_facts", fake_geo
    )
    monkeypatch.setattr("app.assistant.rag_retriever.retrieve_rag_evidence", fake_rag)
    monkeypatch.setattr(
        "app.assistant.service.generate_answer",
        lambda pack, provider=None: "scoped answer",
    )

    # Clear session store between calls
    svc._SESSIONS.clear()

    r1 = svc.ask_assistant(
        db_session,
        "What coal seams are reported in this exploration report?",
        session_id="iso-session",
        document_id="iso-a",
    )
    docs1 = {e.get("source") or e.get("document_name") for e in (r1.get("structured_evidence") or [])}
    rag1 = {e.get("document") or e.get("document_name") for e in (r1.get("rag_evidence") or [])}
    all1 = {*(docs1 - {None}), *(rag1 - {None})}
    assert "Isolation_Beta.pdf" not in all1
    assert "Isolation_Alpha.pdf" in all1 or any("Alpha" in str(x) for x in all1)

    r2 = svc.ask_assistant(
        db_session,
        "What coal seams are reported in this exploration report?",
        session_id="iso-session",
        document_id="iso-b",
    )
    docs2 = {e.get("source") or e.get("document_name") for e in (r2.get("structured_evidence") or [])}
    rag2 = {e.get("document") or e.get("document_name") for e in (r2.get("rag_evidence") or [])}
    all2 = {*(docs2 - {None}), *(rag2 - {None})}
    assert "Isolation_Alpha.pdf" not in all2
    assert "Isolation_Beta.pdf" in all2 or any("Beta" in str(x) for x in all2)
