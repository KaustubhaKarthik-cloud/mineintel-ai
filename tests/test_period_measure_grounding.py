"""Reporting-period and measure-type grounding (no hard-coded org answers)."""

from __future__ import annotations

from pathlib import Path

import fitz

from app.assistant.evidence_filter import (
    evidence_compatible,
    text_matches_measure_type,
    text_matches_reporting_month,
)
from app.assistant.query_router import parse_query
from app.assistant.rag_retriever import retrieve_rag_evidence, _focus_evidence_for_entity
from app.retrieval.table_reconstruct import (
    detect_reporting_month,
    reconstruct_period_production_table,
)


def _pdf(path: Path, text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 50), text, fontsize=8)
    doc.save(path)
    doc.close()
    return path


def _upload(client, path: Path):
    with path.open("rb") as f:
        return client.post(
            "/api/documents/upload",
            files={"file": (path.name, f, "application/pdf")},
            data={"mine_name": "Lab"},
        )


def test_parse_month_and_measure():
    p = parse_query("How much did MineQ produce coal in March of FY25 and FY24?")
    assert p.entity and "mineq" in p.entity.lower().replace(" ", "")
    assert "March" in p.reporting_months
    assert "during" in p.measure_types
    assert any("2025" in x for x in p.periods) and any("2024" in x for x in p.periods)

    p2 = parse_query("What was MineQ coal production upto December FY24?")
    assert "December" in p2.reporting_months
    assert "upto" in p2.measure_types


def test_detect_month_from_page_headers():
    assert detect_reporting_month("Production during Mar\nProduction upto Mar\nFY 25") == "March"
    assert detect_reporting_month("Production during Dec\nDec'24\nFY 25") == "December"
    assert detect_reporting_month("Monthly Coal Statistics for the month of March'2025") == "March"


def test_march_vs_december_not_interchangeable():
    plan = parse_query("How much did MineQ produce coal in March of FY25 and FY24?")
    march = (
        "MineQ coal production | reporting_period=March | measure=during | "
        "FY25=7.07 MT | FY24=6.93 MT."
    )
    dec = (
        "MineQ coal production | reporting_period=December | measure=during | "
        "FY25=5.06 MT | FY24=4.62 MT."
    )
    assert evidence_compatible(plan, march, require_entity=True, require_metric=True).ok
    bad = evidence_compatible(plan, dec, require_entity=True, require_metric=True)
    assert not bad.ok
    assert "reporting_month_mismatch" in bad.reasons


def test_during_vs_upto_not_interchangeable():
    plan = parse_query("What was MineQ coal production during March FY25?")
    assert "during" in plan.measure_types
    during = (
        "MineQ coal production | reporting_period=March | measure=during | "
        "FY25=7.07 MT | FY24=6.93 MT."
    )
    upto = (
        "MineQ coal production | reporting_period=March | measure=upto | "
        "FY25=52.04 MT | FY24=47.56 MT."
    )
    assert evidence_compatible(plan, during, require_entity=True, require_metric=True).ok
    bad = evidence_compatible(plan, upto, require_entity=True, require_metric=True)
    assert not bad.ok
    assert "measure_type_mismatch" in bad.reasons


def test_adjacent_fy_columns_preserved():
    text = """
Production during Mar
Fig. in MT
FY 25
FY 24
1
Basin East
1.10
2.20
▲ 1.00
10.10
20.20
▲ 2.00
2
Basin West
3.30
4.40
▲ 1.00
30.30
40.40
▲ 2.00
3
Basin North
5.50
6.60
▲ 1.00
50.50
60.60
▲ 2.00
Table Coal Production
"""
    recon = reconstruct_period_production_table(text)
    assert recon
    assert "reporting_period=March" in recon
    # FY25 first column, FY24 second — must not swap
    assert "Basin East coal production | reporting_period=March | measure=during | FY25=1.1 MT | FY24=2.2 MT" in recon.replace(
        "1.10", "1.1"
    ).replace("2.20", "2.2") or (
        "FY25=1.1" in recon.replace("1.10", "1.1") and "FY24=2.2" in recon.replace("2.20", "2.2")
    )


def test_focus_filters_month_and_measure():
    blob = (
        "Production table (reconstructed from source layout): "
        "MineQ coal production | reporting_period=March | measure=during | FY25=7.07 MT | FY24=6.93 MT. "
        "MineQ coal production | reporting_period=March | measure=upto | FY25=52.04 MT | FY24=47.56 MT. "
        "MineQ coal production | reporting_period=December | measure=during | FY25=5.06 MT | FY24=4.62 MT."
    )
    plan = parse_query("How much did MineQ produce coal during March FY25?")
    focused = _focus_evidence_for_entity(blob, "MineQ", plan)
    assert "March" in focused and "during" in focused
    assert "7.07" in focused and "6.93" in focused
    assert "52.04" not in focused
    assert "December" not in focused


def test_multi_month_page_retrieval_respects_query_month(client, tmp_path, db_session):
    """Same entity appears in March and December tables — March query must not use Dec."""
    march = _pdf(
        tmp_path / "rep_mar.pdf",
        """
Monthly Statistical Report March'2025
Table 1.1: Coal Production
Production during Mar
Production upto Mar
Fig. in MT
FY 25
Achmt.(%)
FY 24
FY 25
FY 24
1
QuarryZ
5.00
7.07
100.00
6.93
52.04
47.56
2
QuarryY
4.00
4.33
95.00
3.86
40.50
41.10
3
QuarryX
3.00
3.10
90.00
3.00
30.00
29.00
""",
    )
    dec = _pdf(
        tmp_path / "rep_dec.pdf",
        """
Monthly Statistical Report December'2024
Table 1.1: Coal Production
Production during Dec
Production upto Dec
Fig. in MT
FY 25
Achmt.(%)
FY 24
FY 25
FY 24
1
QuarryZ
4.00
5.06
93.00
4.62
33.82
30.01
2
QuarryY
3.00
3.55
88.00
3.63
29.07
29.83
3
QuarryX
2.00
2.10
90.00
2.00
20.00
19.00
""",
    )
    assert _upload(client, march).status_code == 200
    assert _upload(client, dec).status_code == 200

    q = "How much did QuarryZ produce coal in March of FY25 and FY24?"
    plan = parse_query(q)
    assert "March" in plan.reporting_months
    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    assert hits
    blob = " ".join(h.text for h in hits)
    assert "reporting_period=March" in blob or "March" in blob
    assert "7.07" in blob and "6.93" in blob
    # Must not present December values as March evidence
    for h in hits:
        assert "5.06" not in h.text or "December" not in h.text
        if "reporting_period=December" in h.text:
            raise AssertionError("December evidence must not pass March query filter")


def test_missing_period_insufficient(client, tmp_path, db_session):
    path = _pdf(
        tmp_path / "only_dec.pdf",
        """
Production during Dec
FY 25 FY 24
1
ZoneA
1.00
2.00
3.00
4.00
2
ZoneB
5.00
6.00
7.00
8.00
3
ZoneC
9.00
8.00
7.00
6.00
Table Coal Production
""",
    )
    _upload(client, path)
    q = "How much did ZoneA produce coal in March FY25?"
    plan = parse_query(q)
    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    assert all("March" in (h.text or "") or "reporting_period=March" in (h.text or "") for h in hits) or hits == []
    # December-only corpus should yield no March-compatible hits
    assert hits == [] or all("December" not in h.text for h in hits)


def test_unseen_entity_metric_month(client, tmp_path, db_session):
    """Unseen entity/month must come from header-first structured facts, not OCR inventing."""
    from tests.test_structured_table_pipeline import build_production_table_pdf

    path = build_production_table_pdf(
        tmp_path / "unseen.pdf",
        title="Table 1.1: Coal Production",
        month_label="Mar",
        entities=[
            ("Delta Pit", 1.50, 1.40, 1.30, 10.00, 9.00),
            ("Echo Pit", 2.50, 2.40, 2.30, 20.00, 19.00),
            ("Foxtrot Pit", 3.50, 3.40, 3.30, 30.00, 29.00),
        ],
    )
    _upload(client, path)
    q = "How much did Echo Pit produce coal during March FY25 and FY24?"
    plan = parse_query(q)
    assert plan.entity and "echo" in plan.entity.lower()
    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    assert hits
    assert any("Echo Pit" in h.text and "measure=during" in h.text for h in hits)
    assert any("2.4" in h.text for h in hits)  # FY25 during
    assert all("lignite" not in (h.text or "").lower() for h in hits)
