"""Geological analytics — structured aggregation only (no LLM numbers).

Charts/tables are built from GeologicalFact rows with metric-kind compatibility
and provenance. Review-required facts are never silently promoted to verified.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.geology.explorer import (
    PROVISIONAL_STATUSES,
    REJECTED_STATUS,
    VERIFIED_STATUSES,
    _doc_map,
    _doc_meta,
    _formation_ok,
    _row_metric_kind,
    _seam_label,
    _status_bucket,
    document_summary,
    is_resource_fact,
    query_geological_facts,
    resource_value_from_fact,
    to_tonnes,
)
from app.geology.metric_kinds import (
    BOREHOLE_DEPTH,
    FORMATION_THICKNESS,
    MINIMUM_WORKABLE_SEAM_THICKNESS,
    RESOURCE_QUANTITY,
    SEAM_DEPTH,
    SEAM_THICKNESS,
    metrics_compatible,
)
from app.geology.units import canonicalize_length_unit, parse_number, to_metres
from app.models import Document, GeologicalFact


def _empty_analytic(message: str, *, pending: bool = False) -> dict[str, Any]:
    return {
        "items": [],
        "empty": True,
        "message": message,
        "pending_verification": pending,
        "official": False,
    }


def _split_verified_provisional(
    rows: list[GeologicalFact],
) -> tuple[list[GeologicalFact], list[GeologicalFact], bool]:
    """Return (official_rows, display_rows, pending_flag).

    Official analytics prefer verified. If none exist, provisional rows may be
    shown with pending_verification=True. Rejected never included.
    """
    verified = [r for r in rows if r.status in VERIFIED_STATUSES]
    provisional = [r for r in rows if r.status in PROVISIONAL_STATUSES]
    if verified:
        return verified, verified, False
    return [], provisional, True


def resources_by_seam(
    db: Session,
    *,
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    seam: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """Analytic 1 — Seam → Resource from compatible resource facts only."""
    # Load scoped facts (do not require metric_kind=resource — older extracts
    # may store resource quantities only in evidence_text).
    rows = query_geological_facts(
        db,
        document_id=document_id,
        formation=formation,
        seam=seam,
        status=status,
        limit=8000,
    )
    resource_rows: list[GeologicalFact] = []
    for row in rows:
        if not is_resource_fact(row):
            continue
        if not _seam_label(row):
            continue
        resource_rows.append(row)

    official, display, pending = _split_verified_provisional(resource_rows)
    use = official if official else display
    if not use:
        return _empty_analytic(
            "No compatible structured evidence available.",
            pending=False,
        )

    docs = _doc_map(db, {r.document_id for r in use})
    by_seam: dict[str, dict[str, Any]] = {}
    for row in use:
        seam_name = _seam_label(row)
        if not seam_name:
            continue
        val, unit, tonnes = resource_value_from_fact(row)
        if val is None:
            continue
        key = f"{row.document_id}::{seam_name.lower()}"
        existing = by_seam.get(key)
        # Prefer first explicit quantity; do not silently merge incompatible units
        if existing:
            continue
        meta = _doc_meta(docs.get(row.document_id))
        by_seam[key] = {
            "seam": seam_name,
            "value": val,
            "unit": unit,
            "value_tonnes": tonnes,
            "formation": _formation_ok(row.geological_formation, row.evidence_text),
            "document_id": row.document_id,
            "document_name": meta.get("document_name"),
            "page": row.source_page,
            "status": row.status,
            "review_bucket": _status_bucket(row.status),
            "requires_human_verification": _status_bucket(row.status) == "review_required",
            "fact_id": row.id,
            "evidence_text": row.evidence_text,
            "metric_kind": _row_metric_kind(row) or RESOURCE_QUANTITY,
        }

    items = sorted(by_seam.values(), key=lambda x: (x["seam"] or "").lower())
    if not items:
        return _empty_analytic("No compatible structured evidence available.")

    msg = None
    if pending:
        msg = "Data available but pending human verification."

    return {
        "items": items,
        "empty": False,
        "message": msg,
        "pending_verification": pending,
        "official": not pending,
        "chart": {
            "type": "bar",
            "x_key": "seam",
            "y_key": "value",
            "unit_key": "unit",
        },
    }


def formation_seam_distribution(
    db: Session,
    *,
    document_id: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """Analytic 2 — Formation → Seam from explicit structured associations only."""
    rows = query_geological_facts(db, document_id=document_id, status=status, limit=8000)
    # Only rows that have BOTH a plausible formation and a seam label
    linked = []
    for row in rows:
        form = _formation_ok(row.geological_formation, row.evidence_text)
        seam = _seam_label(row)
        if form and seam:
            linked.append(row)

    official, display, pending = _split_verified_provisional(linked)
    use = official if official else display
    if not use:
        # Still show formations without inventing seam links
        return _empty_analytic(
            "No compatible structured evidence available."
            if not linked
            else "Data available but pending human verification.",
            pending=bool(linked) and pending,
        )

    tree: dict[str, dict[str, Any]] = {}
    docs = _doc_map(db, {r.document_id for r in use})
    for row in use:
        form = _formation_ok(row.geological_formation, row.evidence_text)
        seam = _seam_label(row)
        if not form or not seam:
            continue
        entry = tree.setdefault(
            form,
            {
                "formation": form,
                "seams": {},
                "document_ids": set(),
            },
        )
        entry["document_ids"].add(row.document_id)
        seam_entry = entry["seams"].setdefault(
            seam,
            {
                "seam": seam,
                "pages": set(),
                "statuses": set(),
                "fact_ids": [],
                "document_id": row.document_id,
                "document_name": _doc_meta(docs.get(row.document_id)).get("document_name"),
            },
        )
        if row.source_page is not None:
            seam_entry["pages"].add(row.source_page)
        seam_entry["statuses"].add(row.status)
        seam_entry["fact_ids"].append(row.id)

    items = []
    for form, entry in sorted(tree.items(), key=lambda x: x[0].lower()):
        seams = []
        for seam_name, s in sorted(entry["seams"].items(), key=lambda x: x[0].lower()):
            bucket = (
                "verified"
                if s["statuses"] & VERIFIED_STATUSES
                else "review_required"
            )
            seams.append(
                {
                    "seam": seam_name,
                    "source_pages": sorted(s["pages"]),
                    "review_status": bucket,
                    "requires_human_verification": bucket == "review_required",
                    "fact_ids": s["fact_ids"],
                    "document_id": s["document_id"],
                    "document_name": s["document_name"],
                }
            )
        items.append({"formation": form, "seams": seams, "seam_count": len(seams)})

    return {
        "items": items,
        "empty": False,
        "message": "Data available but pending human verification." if pending else None,
        "pending_verification": pending,
        "official": not pending,
    }


def borehole_depth_summary(
    db: Session,
    *,
    document_id: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """Analytic 3 — Borehole → depth using only borehole_depth metric."""
    rows = query_geological_facts(
        db,
        document_id=document_id,
        metric=BOREHOLE_DEPTH,
        status=status,
        limit=8000,
    )
    depth_rows = []
    for row in rows:
        kind = _row_metric_kind(row)
        if kind != BOREHOLE_DEPTH:
            continue
        if not row.borehole_id:
            continue
        if not (row.depth or row.depth_min):
            continue
        # Reject if this looks like seam/formation depth disguised
        if kind in {SEAM_DEPTH, FORMATION_THICKNESS}:
            continue
        depth_rows.append(row)

    official, display, pending = _split_verified_provisional(depth_rows)
    use = official if official else display
    if not use:
        return _empty_analytic(
            "No compatible structured evidence available.",
            pending=False,
        )

    docs = _doc_map(db, {r.document_id for r in use})
    by_bh: dict[str, dict[str, Any]] = {}
    for row in use:
        key = f"{row.document_id}::{(row.borehole_id or '').upper()}"
        if key in by_bh:
            continue  # do not silently merge different depth semantics
        if row.depth_min and row.depth_max:
            val = f"{row.depth_min}–{row.depth_max}"
            norm = row.depth_min_normalized_m
        else:
            val = str(row.depth)
            norm = row.depth_normalized_m
            if norm is None:
                num = parse_number(str(row.depth))
                norm = to_metres(num, row.depth_unit) if num is not None else None
        meta = _doc_meta(docs.get(row.document_id))
        by_bh[key] = {
            "borehole_id": row.borehole_id,
            "value": val,
            "unit": row.depth_unit,
            "value_m": norm,
            "metric_kind": BOREHOLE_DEPTH,
            "document_id": row.document_id,
            "document_name": meta.get("document_name"),
            "page": row.source_page,
            "status": row.status,
            "review_bucket": _status_bucket(row.status),
            "requires_human_verification": _status_bucket(row.status) == "review_required",
            "fact_id": row.id,
            "evidence_text": row.evidence_text,
        }

    items = sorted(by_bh.values(), key=lambda x: (x["borehole_id"] or "").lower())
    return {
        "items": items,
        "empty": not items,
        "message": (
            "Data available but pending human verification."
            if pending
            else (None if items else "No compatible structured evidence available.")
        ),
        "pending_verification": pending,
        "official": not pending and bool(items),
        "chart": {"type": "bar", "x_key": "borehole_id", "y_key": "value", "unit_key": "unit"},
    }


def seam_thickness_analytic(
    db: Session,
    *,
    document_id: Optional[str] = None,
    seam: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """Analytic 4 — Seam thickness from compatible seam_thickness only."""
    rows = query_geological_facts(
        db,
        document_id=document_id,
        seam=seam,
        metric=SEAM_THICKNESS,
        status=status,
        limit=8000,
    )
    thickness_rows = []
    for row in rows:
        kind = _row_metric_kind(row)
        # Hard exclusions
        if kind in {
            MINIMUM_WORKABLE_SEAM_THICKNESS,
            FORMATION_THICKNESS,
            "seam_parting_thickness",
            "overburden_thickness",
        }:
            continue
        if not metrics_compatible(SEAM_THICKNESS, kind):
            continue
        if kind != SEAM_THICKNESS:
            continue
        if not _seam_label(row):
            continue
        if not (row.thickness or row.thickness_min):
            continue
        thickness_rows.append(row)

    official, display, pending = _split_verified_provisional(thickness_rows)
    use = official if official else display
    if not use:
        return _empty_analytic(
            "No compatible seam-thickness evidence available.",
            pending=False,
        )

    docs = _doc_map(db, {r.document_id for r in use})
    by_seam: dict[str, dict[str, Any]] = {}
    for row in use:
        seam_name = _seam_label(row)
        if not seam_name:
            continue
        key = f"{row.document_id}::{seam_name.lower()}"
        if key in by_seam:
            continue
        if row.thickness_min and row.thickness_max:
            val = f"{row.thickness_min}–{row.thickness_max}"
            norm = row.thickness_min_normalized_m
        else:
            val = str(row.thickness)
            norm = row.thickness_normalized_m
            if norm is None:
                num = parse_number(str(row.thickness))
                norm = to_metres(num, row.thickness_unit) if num is not None else None
        meta = _doc_meta(docs.get(row.document_id))
        by_seam[key] = {
            "seam": seam_name,
            "value": val,
            "unit": row.thickness_unit or canonicalize_length_unit(row.thickness_unit) or "m",
            "value_m": norm,
            "metric_kind": SEAM_THICKNESS,
            "document_id": row.document_id,
            "document_name": meta.get("document_name"),
            "page": row.source_page,
            "status": row.status,
            "review_bucket": _status_bucket(row.status),
            "requires_human_verification": _status_bucket(row.status) == "review_required",
            "fact_id": row.id,
            "evidence_text": row.evidence_text,
        }

    items = sorted(by_seam.values(), key=lambda x: (x["seam"] or "").lower())
    return {
        "items": items,
        "empty": not items,
        "message": (
            "Data available but pending human verification."
            if pending
            else (None if items else "No compatible seam-thickness evidence available.")
        ),
        "pending_verification": pending,
        "official": not pending and bool(items),
        "chart": {"type": "bar", "x_key": "seam", "y_key": "value", "unit_key": "unit"},
    }


def geological_fact_summary(
    db: Session,
    *,
    document_id: Optional[str] = None,
) -> dict[str, Any]:
    """Analytic 5 — compact summary from structured data only."""
    if document_id:
        summary = document_summary(db, document_id)
        return {
            "formations_identified": summary.get("formation_count", 0),
            "seams_identified": summary.get("seam_count", 0),
            "boreholes_identified": summary.get("borehole_count", 0),
            "resources_available": summary.get("resource_fact_count", 0),
            "review_required_facts": summary.get("review_required_count", 0),
            "documents_represented": 1,
            "pending_verification": summary.get("pending_verification", False),
            "document": {
                "document_id": summary.get("document_id"),
                "document_name": summary.get("document_name"),
                "document_type": summary.get("document_type"),
            },
        }

    from app.geology.explorer import list_geological_documents

    docs = list_geological_documents(db)
    return {
        "formations_identified": sum(d.get("formation_count") or 0 for d in docs),
        "seams_identified": sum(d.get("seam_count") or 0 for d in docs),
        "boreholes_identified": sum(d.get("borehole_count") or 0 for d in docs),
        "resources_available": sum(d.get("resource_fact_count") or 0 for d in docs),
        "review_required_facts": sum(d.get("review_required_count") or 0 for d in docs),
        "documents_represented": len(docs),
        "pending_verification": any(d.get("pending_verification") for d in docs),
        "documents": [
            {
                "document_id": d.get("document_id"),
                "document_name": d.get("document_name"),
                "document_type": d.get("document_type"),
            }
            for d in docs
        ],
    }


def compare_documents(
    db: Session,
    document_id_a: str,
    document_id_b: str,
    *,
    metrics: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Factual side-by-side comparison — no ranking."""
    if document_id_a == document_id_b:
        return {
            "error": "Select two different documents.",
            "items": [],
        }
    doc_a = db.get(Document, document_id_a)
    doc_b = db.get(Document, document_id_b)
    if not doc_a or not doc_b:
        return {"error": "One or both documents were not found.", "items": []}

    wanted = set(m.lower() for m in (metrics or [
        "formations",
        "seams",
        "resources",
        "boreholes",
        "borehole_depths",
        "minimum_workable_thickness",
    ]))

    side_a = _document_compare_side(db, doc_a, wanted)
    side_b = _document_compare_side(db, doc_b, wanted)

    comparisons = []
    for key in sorted(wanted):
        a_val = side_a.get(key)
        b_val = side_b.get(key)
        comparisons.append(
            {
                "metric": key,
                "compatible": True,  # each side keeps own metric semantics
                "document_a": a_val,
                "document_b": b_val,
            }
        )

    return {
        "document_a": _doc_meta(doc_a),
        "document_b": _doc_meta(doc_b),
        "comparisons": comparisons,
        "note": "Factual comparison only — documents are not ranked.",
    }


def _document_compare_side(
    db: Session, doc: Document, wanted: set[str]
) -> dict[str, Any]:
    summary = document_summary(db, doc.id)
    out: dict[str, Any] = {}
    meta = _doc_meta(doc)

    if "formations" in wanted:
        from app.geology.explorer import list_formations

        forms = list_formations(db, document_id=doc.id)
        out["formations"] = {
            "count": len(forms),
            "names": [f["formation_name"] for f in forms],
            "evidence": [
                {
                    "value": f["formation_name"],
                    "pages": f["source_pages"],
                    "status": f["review_status"],
                    "document_id": doc.id,
                    "document_name": meta.get("document_name"),
                }
                for f in forms
            ],
        }

    if "seams" in wanted:
        from app.geology.explorer import list_seams

        seams = list_seams(db, document_id=doc.id)
        out["seams"] = {
            "count": len(seams),
            "names": [s["seam_name"] for s in seams],
            "evidence": [
                {
                    "value": s["seam_name"],
                    "pages": s["source_pages"],
                    "status": s["review_status"],
                    "document_id": doc.id,
                    "document_name": meta.get("document_name"),
                }
                for s in seams
            ],
        }

    if "resources" in wanted:
        res = resources_by_seam(db, document_id=doc.id)
        out["resources"] = {
            "count": len(res.get("items") or []),
            "items": res.get("items") or [],
            "pending_verification": res.get("pending_verification"),
            "message": res.get("message"),
        }

    if "boreholes" in wanted:
        from app.geology.explorer import list_boreholes

        bhs = list_boreholes(db, document_id=doc.id)
        out["boreholes"] = {
            "count": len(bhs),
            "ids": [b["borehole_id"] for b in bhs],
            "evidence": [
                {
                    "value": b["borehole_id"],
                    "pages": b["source_pages"],
                    "status": b["review_status"],
                    "document_id": doc.id,
                    "document_name": meta.get("document_name"),
                }
                for b in bhs
            ],
        }

    if "borehole_depths" in wanted:
        depths = borehole_depth_summary(db, document_id=doc.id)
        out["borehole_depths"] = {
            "count": len(depths.get("items") or []),
            "items": depths.get("items") or [],
            "message": depths.get("message"),
        }

    if "minimum_workable_thickness" in wanted:
        rows = query_geological_facts(
            db,
            document_id=doc.id,
            metric=MINIMUM_WORKABLE_SEAM_THICKNESS,
            limit=100,
        )
        items = []
        for row in rows:
            kind = _row_metric_kind(row)
            if kind != MINIMUM_WORKABLE_SEAM_THICKNESS:
                continue
            if row.status == REJECTED_STATUS:
                continue
            val = None
            if row.thickness:
                val = str(row.thickness)
            elif row.thickness_min and row.thickness_max:
                val = f"{row.thickness_min}–{row.thickness_max}"
            if not val:
                continue
            items.append(
                {
                    "value": val,
                    "unit": row.thickness_unit,
                    "page": row.source_page,
                    "status": row.status,
                    "fact_id": row.id,
                    "evidence_text": row.evidence_text,
                    "document_id": doc.id,
                    "document_name": meta.get("document_name"),
                    "metric_kind": MINIMUM_WORKABLE_SEAM_THICKNESS,
                }
            )
        out["minimum_workable_thickness"] = {
            "count": len(items),
            "items": items,
            "message": None
            if items
            else "No compatible structured evidence available.",
        }

    out["summary"] = summary
    return out


def analytics_bundle(
    db: Session,
    *,
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    seam: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "summary": geological_fact_summary(db, document_id=document_id),
        "resources_by_seam": resources_by_seam(
            db, document_id=document_id, formation=formation, seam=seam
        ),
        "formation_seam": formation_seam_distribution(db, document_id=document_id),
        "borehole_depths": borehole_depth_summary(db, document_id=document_id),
        "seam_thickness": seam_thickness_analytic(
            db, document_id=document_id, seam=seam
        ),
    }


EXPLAIN_SYSTEM_PROMPT = """You are MineIntel AI explaining geological analytics.

Hard rules:
1. Use ONLY the structured evidence supplied in the user message.
2. Do NOT invent numerical values, seam names, formations, borehole IDs, or pages.
3. Do NOT recalculate or invent chart values — describe only what the evidence shows.
4. If evidence is insufficient, say so clearly.
5. Cite document name and page when present.
6. Never promote review_required / pending facts as verified.
7. Do not rank documents as better or worse.
"""


def explain_analytics(
    *,
    question: str,
    evidence: dict[str, Any],
    provider=None,
) -> dict[str, Any]:
    """LLM explanation over supplied analytics evidence — never invents numbers."""
    from app.assistant.providers import LLMError, get_assistant_llm

    items = evidence.get("items") or evidence.get("comparisons") or []
    if not items and evidence.get("empty", True) and not evidence.get("summary"):
        return {
            "explanation": "Insufficient compatible evidence was found to explain.",
            "evidence_used": evidence,
            "provider": "none",
        }

    # Build a deterministic evidence block for the LLM
    lines = ["STRUCTURED ANALYTICS EVIDENCE (do not invent values beyond this):"]
    if evidence.get("pending_verification"):
        lines.append("NOTE: Data is pending human verification.")
    if evidence.get("message"):
        lines.append(f"STATUS: {evidence['message']}")
    for i, item in enumerate(items[:40], 1):
        if not isinstance(item, dict):
            lines.append(f"{i}. {item}")
            continue
        parts = []
        for k in (
            "seam",
            "formation",
            "borehole_id",
            "value",
            "unit",
            "document_name",
            "page",
            "status",
            "metric",
            "metric_kind",
        ):
            if item.get(k) is not None:
                parts.append(f"{k}={item[k]}")
        # Nested compare sides
        if item.get("document_a") or item.get("document_b"):
            parts.append(f"metric={item.get('metric')}")
            parts.append(f"a={item.get('document_a')}")
            parts.append(f"b={item.get('document_b')}")
        if item.get("seams"):
            parts.append(
                "seams="
                + ",".join(
                    s.get("seam") or ""
                    for s in item["seams"]
                    if isinstance(s, dict)
                )
            )
        if item.get("evidence_text"):
            parts.append(f"evidence={str(item['evidence_text'])[:200]}")
        lines.append(f"{i}. " + " | ".join(parts))

    if evidence.get("summary"):
        lines.append(f"SUMMARY: {evidence['summary']}")

    user_prompt = (
        f"USER QUESTION: {question}\n\n"
        + "\n".join(lines)
        + "\n\nExplain the analytics using only the evidence above."
    )

    llm = provider or get_assistant_llm()
    try:
        # Mock provider echoes user_prompt — produce a grounded template instead
        if getattr(llm, "name", "") == "mock":
            explanation = _mock_explain(question, evidence, items)
        else:
            explanation = llm.generate(EXPLAIN_SYSTEM_PROMPT, user_prompt)
    except LLMError as exc:
        explanation = (
            _mock_explain(question, evidence, items)
            + f" (LLM unavailable: {exc})"
        )

    return {
        "explanation": explanation,
        "evidence_used": {
            "item_count": len(items),
            "pending_verification": evidence.get("pending_verification"),
            "items": items[:40],
        },
        "provider": getattr(llm, "name", "unknown"),
    }


def _mock_explain(question: str, evidence: dict[str, Any], items: list) -> str:
    if not items:
        return "Insufficient compatible evidence was found to explain."
    lines = ["Based on the supplied structured evidence:"]
    if evidence.get("pending_verification"):
        lines.append("These facts are pending human verification.")
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        label = (
            item.get("seam")
            or item.get("formation")
            or item.get("borehole_id")
            or item.get("metric")
            or "item"
        )
        val = item.get("value")
        unit = item.get("unit") or ""
        page = item.get("page")
        doc = item.get("document_name") or ""
        bit = f"- {label}"
        if val is not None:
            bit += f": {val} {unit}".rstrip()
        if item.get("seams"):
            bit += " → " + ", ".join(
                s.get("seam") or "" for s in item["seams"] if isinstance(s, dict)
            )
        if doc:
            bit += f" ({doc}"
            if page is not None:
                bit += f", p.{page}"
            bit += ")"
        elif page is not None:
            bit += f" (p.{page})"
        lines.append(bit)
    lines.append("No values were invented beyond the structured evidence.")
    return "\n".join(lines)
