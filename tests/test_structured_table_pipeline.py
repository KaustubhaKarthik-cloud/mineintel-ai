"""Header-first structured table pipeline tests (generic, no org hard-codes)."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.assistant.evidence_filter import evidence_compatible
from app.assistant.query_router import parse_query
from app.assistant.rag_retriever import retrieve_rag_evidence
from app.retrieval.structured_table import (
    StructuredFact,
    extract_facts_from_pdf_page,
    parse_table_matrix,
)


def build_production_table_pdf(
    path: Path,
    *,
    title: str,
    month_label: str,
    entities: list[tuple[str, float, float, float, float, float]],
    fy_order: tuple[str, str] = ("FY 25", "FY 24"),
) -> Path:
    """Draw a bordered MoC-like production table so find_tables can extract it.

    entities: (name, target, during_fy_a, during_fy_b, upto_fy_a, upto_fy_b)
    fy_order controls which FY label is first under during/upto.
    """
    doc = fitz.open()
    page = doc.new_page(width=700, height=500)
    page.insert_text((40, 36), title, fontsize=11)
    headers_top = [
        "Sl No",
        "Subs",
        "Monthly Target",
        f"Production during {month_label}",
        f"Production during {month_label}",
        f"Production during {month_label}",
        f"Production during {month_label}",
        f"Production upto {month_label}",
        f"Production upto {month_label}",
        f"Production upto {month_label}",
    ]
    headers_sub = [
        "",
        "",
        "",
        fy_order[0],
        "Achmt.(%)",
        fy_order[1],
        "Growth (%)",
        fy_order[0],
        fy_order[1],
        "Growth (%)",
    ]
    # Column x positions — wider cells so header text fits
    xs = [30, 70, 150, 230, 300, 370, 440, 510, 580, 650, 720]
    y0 = 60
    row_h = 28
    n_rows = 2 + len(entities)

    def draw_row(yi: int, cells: list[str], bold: bool = False):
        y = y0 + yi * row_h
        for i in range(len(xs) - 1):
            rect = fitz.Rect(xs[i], y, xs[i + 1], y + row_h)
            page.draw_rect(rect, color=(0, 0, 0), width=0.5)
            txt = cells[i] if i < len(cells) else ""
            if txt:
                page.insert_textbox(
                    rect + (1, 2, -1, -1),
                    txt,
                    fontsize=6,
                    align=fitz.TEXT_ALIGN_CENTER,
                )

    draw_row(0, headers_top)
    draw_row(1, headers_sub)
    for i, (name, tgt, d_a, d_b, u_a, u_b) in enumerate(entities):
        ach = f"{(d_a / tgt * 100) if tgt else 0:.2f}"
        cells = [
            str(i + 1),
            name,
            f"{tgt:.2f}",
            f"{d_a:.2f}",
            ach,
            f"{d_b:.2f}",
            "0.00",
            f"{u_a:.2f}",
            f"{u_b:.2f}",
            "0.00",
        ]
        draw_row(2 + i, cells)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def test_parse_matrix_preserves_fy_and_measure_order():
    # FY24 before FY25 under during/upto
    matrix = [
        ["Sl No", "Subs", "Monthly Target", "Production during Mar", None, None, None, "Production upto Mar", None, None],
        [None, None, None, "FY 24", "Achmt.(%)", "FY 25", "Growth", "FY 24", "FY 25", "Growth"],
        ["1", "Alpha Co", "1.00", "0.90", "90", "1.10", "0", "9.00", "11.00", "0"],
    ]
    facts = parse_table_matrix(
        matrix,
        page=1,
        table_index=0,
        page_text="Table 9.9: Coal Production",
        table_title="Table 9.9: Coal Production",
    )
    during = {(f.fiscal_year, f.value) for f in facts if f.entity == "Alpha Co" and f.measurement_type == "during"}
    upto = {(f.fiscal_year, f.value) for f in facts if f.entity == "Alpha Co" and f.measurement_type == "upto"}
    assert ("FY2024", 0.9) in during
    assert ("FY2025", 1.1) in during
    assert ("FY2024", 9.0) in upto
    assert ("FY2025", 11.0) in upto


def test_property_incompatible_dimensions_rejected():
    base = StructuredFact(
        entity="Alpha Co",
        metric="coal",
        reporting_month="March",
        fiscal_year="FY2025",
        measurement_type="during",
        value=1.23,
        unit="MT",
        page=1,
        table_id="p1:t0",
        table_title="Coal Production",
        row_label="Alpha Co",
        column_path="Production during Mar / FY 25",
        confidence=0.9,
    )
    plan = parse_query("How much did Alpha Co produce coal during March FY25?")
    assert evidence_compatible(plan, base.to_evidence_text(), meta=base.to_meta() | {"structured_fact": True}).ok

    # Month change
    bad_m = StructuredFact(**{**base.__dict__, "reporting_month": "December"})
    assert not evidence_compatible(
        plan, bad_m.to_evidence_text(), meta=bad_m.to_meta() | {"structured_fact": True}
    ).ok

    # FY change
    bad_fy = StructuredFact(**{**base.__dict__, "fiscal_year": "FY2024"})
    plan_fy25 = parse_query("Alpha Co coal during March FY25?")
    assert not evidence_compatible(
        plan_fy25, bad_fy.to_evidence_text(), meta=bad_fy.to_meta() | {"structured_fact": True},
        require_period=True, active_periods=["FY2025"],
    ).ok

    # Measure change
    bad_meas = StructuredFact(**{**base.__dict__, "measurement_type": "upto"})
    assert not evidence_compatible(
        plan, bad_meas.to_evidence_text(), meta=bad_meas.to_meta() | {"structured_fact": True}
    ).ok

    # Entity change
    bad_ent = StructuredFact(**{**base.__dict__, "entity": "Beta Co"})
    assert not evidence_compatible(
        plan, bad_ent.to_evidence_text(), meta=bad_ent.to_meta() | {"structured_fact": True}
    ).ok

    # Metric change (lignite)
    bad_met = StructuredFact(**{**base.__dict__, "metric": "lignite"})
    assert not evidence_compatible(
        plan, bad_met.to_evidence_text(), meta=bad_met.to_meta() | {"structured_fact": True}
    ).ok


def test_cil_substring_does_not_match_nlcil():
    plan = parse_query("How much did CIL produce coal in March of FY25 and FY24?")
    nlcil = (
        "STRUCTURED_FACT | entity=NLCIL | metric=lignite | reporting_period=March | "
        "measure=during | fiscal_year=FY2025 | value=2.91 | unit=MT"
    )
    meta = {
        "structured_fact": True,
        "entity": "NLCIL",
        "metric": "lignite",
        "reporting_month": "March",
        "fiscal_year": "FY2025",
        "measurement_type": "during",
        "value": 2.91,
        "unit": "MT",
    }
    bad = evidence_compatible(plan, nlcil, meta=meta)
    assert not bad.ok


def test_pdf_table_roundtrip_extract(tmp_path):
    path = build_production_table_pdf(
        tmp_path / "round.pdf",
        title="Table 2.2: Coal Production",
        month_label="Mar",
        entities=[("Echo Pit", 2.50, 2.40, 2.30, 20.00, 19.00)],
    )
    facts = extract_facts_from_pdf_page(path, 1)
    echo = [f for f in facts if "Echo" in f.entity]
    assert echo, f"expected Echo Pit facts, got {facts}"
    during = {f.fiscal_year: f.value for f in echo if f.measurement_type == "during"}
    assert during.get("FY2025") == pytest.approx(2.40)
    assert during.get("FY2024") == pytest.approx(2.30)


def test_e2e_structured_fact_retrieval(client, tmp_path, db_session):
    path = build_production_table_pdf(
        tmp_path / "e2e.pdf",
        title="Table 3.3: Coal Production",
        month_label="Dec",
        entities=[("Gamma Mine", 5.0, 4.5, 4.0, 40.0, 38.0)],
        fy_order=("FY 24", "FY 25"),  # reversed FY order
    )
    with path.open("rb") as f:
        client.post(
            "/api/documents/upload",
            files={"file": (path.name, f, "application/pdf")},
            data={"mine_name": "Lab"},
        )
    q = "How much did Gamma Mine produce coal during December FY25?"
    plan = parse_query(q)
    hits = retrieve_rag_evidence(db_session, q, plan=plan, top_k=5)
    assert hits
    assert any("Gamma Mine" in h.text and "measure=during" in h.text for h in hits)
    assert any("4.0" in h.text or "4" in h.text for h in hits)
    # March must not appear as reporting period
    assert all("reporting_period=March" not in (h.text or "") for h in hits)
