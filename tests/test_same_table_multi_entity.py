"""Same-table multi-entity provenance regression (real PDF Table 1.1).

Verifies every subsidiary row on the CIL source table is independently
extractable and retrievable — no entity favoritism / hard-coded allowlist.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.assistant.evidence_filter import evidence_compatible, text_matches_entity
from app.assistant.pdf_fact_retriever import retrieve_pdf_structured_facts
from app.assistant.query_router import parse_query
from app.retrieval.structured_table import extract_facts_from_pdf_page

REAL_PDF = Path(
    r"C:\Users\karth\Documents\original\bda7ac26-0d0f-41b0-94c2-13089aca9c4e_srn-march-2025.pdf"
)


@pytest.fixture(scope="module")
def page5_matrix_entities():
    if not REAL_PDF.is_file():
        pytest.skip("srn-march-2025.pdf not available")
    doc = fitz.open(str(REAL_PDF))
    page = doc[4]
    tabs = list(page.find_tables().tables)
    assert tabs, "expected table on page 5"
    matrix = tabs[0].extract()
    doc.close()
    entities = []
    for row in matrix[2:]:
        # label usually col 0 or 1
        for cell in row[:2]:
            lab = (cell or "").strip()
            if not lab:
                continue
            if lab.replace(".", "").isdigit():
                continue
            if lab.lower() in {"grand total", "total", "subs", "sl no"}:
                continue
            entities.append(lab)
            break
    assert "CIL" in entities
    assert "ECL" in entities
    return entities


def test_same_table_all_rows_become_structured_facts(page5_matrix_entities):
    facts = extract_facts_from_pdf_page(REAL_PDF, 5)
    during = [
        f
        for f in facts
        if f.measurement_type == "during" and f.metric == "coal" and f.fiscal_year == "FY2025"
    ]
    fact_entities = {f.entity for f in during}
    missing = [e for e in page5_matrix_entities if e not in fact_entities]
    assert not missing, f"table rows lost during structured extraction: {missing}"


def test_same_table_entities_independently_compatible(page5_matrix_entities):
    """Each row must pass evidence compat for its own query — not only CIL."""
    facts = extract_facts_from_pdf_page(REAL_PDF, 5)
    sample = [e for e in page5_matrix_entities if e.upper() in {"CIL", "ECL", "BCCL", "CCL", "NEC"}]
    assert len(sample) >= 4
    for ent in sample:
        plan = parse_query(f"How much did {ent} produce coal in March of FY25?")
        assert plan.entity and text_matches_entity(plan.entity, ent)
        matches = [
            f
            for f in facts
            if text_matches_entity(f.entity, ent)
            and f.measurement_type == "during"
            and f.fiscal_year == "FY2025"
            and f.metric == "coal"
        ]
        assert matches, f"no structured fact for {ent}"
        f = matches[0]
        meta = {**f.to_meta(), "structured_fact": True}
        compat = evidence_compatible(plan, f.to_evidence_text(), meta=meta)
        assert compat.ok, f"{ent} rejected: {compat.reasons}"


def test_slash_entity_name_parsed(page5_matrix_entities):
    if "Captive/Others" not in page5_matrix_entities:
        pytest.skip("Captive/Others not in matrix")
    plan = parse_query(
        "How much did Captive/Others produce coal in March of FY25 and FY24?"
    )
    assert plan.entity
    assert "captive" in plan.entity.lower()
    assert "/" in plan.entity or "others" in plan.entity.lower()


def test_cil_not_special_cased_vs_ecl(page5_matrix_entities):
    """Side-by-side: CIL and ECL must both extract with same month/measure/FY dims."""
    facts = extract_facts_from_pdf_page(REAL_PDF, 5)

    def dims(ent: str):
        return {
            (f.reporting_month, f.fiscal_year, f.measurement_type, f.metric)
            for f in facts
            if f.entity == ent
        }

    cil = dims("CIL")
    ecl = dims("ECL")
    # Shared during/upto × FY25/FY24 × coal × March should exist for both
    shared = cil & ecl
    assert ("March", "FY2025", "during", "coal") in shared
    assert ("March", "FY2024", "during", "coal") in shared
