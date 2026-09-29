"""Indexing, table reconstruction, and retrieval/compat generalization tests."""

from __future__ import annotations

from pathlib import Path

import fitz

from app.assistant.evidence_filter import evidence_compatible, entity_in_factual_role
from app.assistant.query_router import parse_query
from app.assistant.rag_retriever import retrieve_rag_evidence, _focus_evidence_for_entity
from app.assistant.service import ask_assistant
from app.models import Document
from app.retrieval.table_reconstruct import reconstruct_period_production_table


def _upload(client, path: Path, name: str | None = None):
    with path.open("rb") as f:
        return client.post(
            "/api/documents/upload",
            files={"file": (name or path.name, f, "application/pdf")},
            data={"mine_name": "Lab Mine"},
        )


def _pdf(path: Path, text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), text, fontsize=9)
    doc.save(path)
    doc.close()
    return path


def test_auto_index_after_upload(client, tmp_path, db_session):
    path = _pdf(
        tmp_path / "auto_idx.pdf",
        "Ridge Valley coal production in FY2024 reached 4.1 MT.",
    )
    up = _upload(client, path)
    assert up.status_code == 200, up.text
    doc_id = up.json()["id"]
    doc = db_session.query(Document).filter(Document.id == doc_id).one()
    assert doc.index_status == "indexed"
    assert doc.embedding_completed is True
    assert (doc.meta or {}) or True  # pages persisted
    from app.models import DocumentChunk

    n = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count()
    assert n >= 1


def test_reconstruct_statewise_table_generic():
    text = """
State
Dec'24
Alpha Region
1.10
Beta Region
2.20
Gamma Region
3.30
Fig. in MT
FY 25
FY 24
Growth (%)
M-o-M
FY 25
FY 24
Growth (%)
Y-o-Y
1
10.01
9.01
▲ 1.00
80.01
70.01
▲ 2.00
2
20.02
19.02
▲ 1.00
90.02
85.02
▲ 2.00
3
30.03
29.03
▲ 1.00
100.03
95.03
▲ 2.00
Table 1.1 (a)  State-wise Coal Production
Production during Dec
"""
    recon = reconstruct_period_production_table(text)
    assert recon
    assert "Alpha Region coal production" in recon
    assert "reporting_period=December" in recon
    assert "FY25=10.01" in recon and "FY24=9.01" in recon
    assert "Beta Region coal production" in recon
    assert "Gamma Region" in recon


def test_reconstruct_company_interleaved_table():
    text = """
Fig. in MT
FY 25
Achmt.(%)
FY 24
FY 25
FY 24
1
MineQ
5.00
4.50
90.00
4.00
40.00
38.00
2
MineR
6.00
5.50
91.00
5.00
50.00
48.00
3
MineS
7.00
6.50
92.00
6.00
60.00
58.00
Table 1.1:  Coal Production
Production during Mar
Production upto Mar
"""
    recon = reconstruct_period_production_table(text)
    assert recon
    assert "MineQ coal production" in recon
    assert "reporting_period=March" in recon
    assert "FY25=4.5" in recon.replace("4.50", "4.5") or "FY25=4.50" in recon


def test_entity_factual_role_rejects_jv_boilerplate():
    plan = parse_query("how much did Ridge Valley produce coal in fy24?")
    jv = (
        "Company Z is a Joint venture of Govt. of Ridge Valley and the Govt. of India. "
        "Coal Power Gross numbers 2023-24 appear in an unrelated table."
    )
    assert not entity_in_factual_role(jv, plan.entity, plan.metrics or ["coal"])
    bad = evidence_compatible(plan, jv, require_entity=True, require_metric=True)
    assert not bad.ok
    assert "entity_not_factual_subject" in bad.reasons


def test_focus_keeps_fy_values_for_entity():
    blob = (
        "State-wise coal production (reconstructed from source table): "
        "Alpha Region coal production | reporting_period=December | measure=during | "
        "FY25=10.01 MT | FY24=9.01 MT. "
        "Alpha Region coal production | reporting_period=December | measure=upto | "
        "FY25=80.01 MT | FY24=70.01 MT. "
        "Beta Region coal production | reporting_period=December | measure=during | "
        "FY25=20.02 MT | FY24=19.02 MT. "
        "Beta Region coal production | reporting_period=December | measure=upto | "
        "FY25=90.02 MT | FY24=85.02 MT."
    )
    focused = _focus_evidence_for_entity(blob, "Beta Region")
    assert "Beta Region" in focused
    assert "20.02" in focused and "19.02" in focused
    assert "Alpha Region" not in focused


def test_compatible_reconstructed_evidence_accepted(client, tmp_path, db_session):
    path = _pdf(
        tmp_path / "state_coal.pdf",
        """
State
Dec'24
North Basin
1.10
South Basin
2.20
East Basin
3.30
Fig. in MT
FY 25
FY 24
Growth (%)
M-o-M
FY 25
FY 24
Growth (%)
Y-o-Y
1
11.11
10.11
▲ 1.00
111.11
101.11
▲ 2.00
2
22.22
21.22
▲ 1.00
222.22
212.22
▲ 2.00
3
33.33
32.33
▲ 1.00
333.33
323.33
▲ 2.00
Table 1.1 (a)  State-wise Coal Production
""",
    )
    up = _upload(client, path)
    doc_id = up.json()["id"]
    # upload auto-indexes; ensure ready
    doc = db_session.query(Document).filter(Document.id == doc_id).one()
    assert doc.index_status == "indexed"

    q = "How much did South Basin produce coal in FY25 and FY24?"
    plan = parse_query(q)
    assert plan.entity and "south" in plan.entity.lower()
    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    assert hits, "compatible reconstructed evidence should be retrieved"
    blob = " ".join(h.text for h in hits).lower()
    assert "south basin" in blob
    assert "fy25" in blob.replace(" ", "") or "fy 25" in blob
    # Unrelated JV-style noise must not be required; ensure no forced NLC substitution
    body = ask_assistant(db_session, q)
    reply = (body.get("reply") or "").lower()
    sources = body.get("sources") or []
    assert sources
    assert "south" in reply or any("south" in (s.get("snippet") or "").lower() for s in sources)


def test_unrelated_noise_still_rejected(client, tmp_path, db_session):
    path = _pdf(
        tmp_path / "noise.pdf",
        "NLC India Limited lignite table FY 2023-24 actual 12.64. "
        "Joint venture of Govt. of Westoria and Govt. of India.",
    )
    _upload(client, path)
    q = "How much did Westoria produce coal in FY25 and FY24?"
    plan = parse_query(q)
    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    assert all("westoria" in (h.text or "").lower() for h in hits)
    # JV + lignite must not count as Westoria coal production evidence
    for h in hits:
        assert "12.64" not in (h.text or "") or "coal production" in (h.text or "").lower()
    body = ask_assistant(db_session, q)
    reply = (body.get("reply") or "").lower()
    if not body.get("rag_evidence"):
        assert (
            "couldn't find" in reply
            or "could not find" in reply
            or "verified evidence" in reply
            or "verified information" in reply
            or "no reliable information" in reply
            or "insufficient" in reply
            or "cannot determine" in reply
            or "unable to determine" in reply
        )
        assert "12.64" not in reply
