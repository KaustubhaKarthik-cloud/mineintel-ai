"""Read-only adapter: GeologicalFact → Analytics-compatible structured rows.

Does NOT invent values from RAG text.
Does NOT promote review_required to verified.
Reuses existing GeologicalFact rows only.
"""

from __future__ import annotations

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
    is_resource_fact,
    list_geological_documents,
    query_geological_facts,
    resource_value_from_fact,
)
from app.geology.metric_kinds import (
    BOREHOLE,
    BOREHOLE_DEPTH,
    FORMATION,
    MINIMUM_WORKABLE_SEAM_THICKNESS,
    RESERVE_QUANTITY,
    RESOURCE_QUANTITY,
    SEAM,
    SEAM_DEPTH,
    SEAM_THICKNESS,
)
from app.geology.semantic import (
    NO_STRUCTURED_GEOLOGICAL,
    geo_metric_label,
    normalize_geo_metric,
    workable_thickness_value_from_fact,
)
from app.models import Document, GeologicalFact


def _display_value(row: GeologicalFact, kind: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """Return (display_value, unit, numeric_hint) from structured fields only."""
    if row.corrected_value:
        return str(row.corrected_value), row.corrected_unit or row.original_unit, None
    if kind in {RESOURCE_QUANTITY, RESERVE_QUANTITY, "resource", "reserve"} or is_resource_fact(row):
        val, unit, tonnes = resource_value_from_fact(row)
        if val is not None:
            try:
                num = float(val)
            except (TypeError, ValueError):
                num = tonnes
            return str(val), unit, num
    if row.thickness_min and row.thickness_max:
        return f"{row.thickness_min}–{row.thickness_max}", row.thickness_unit, row.thickness_min_normalized_m
    if row.thickness:
        num = row.thickness_normalized_m
        return str(row.thickness), row.thickness_unit, num
    if kind == MINIMUM_WORKABLE_SEAM_THICKNESS:
        val, unit = workable_thickness_value_from_fact(
            thickness=row.thickness,
            thickness_unit=row.thickness_unit,
            thickness_min=row.thickness_min,
            thickness_max=row.thickness_max,
            corrected_value=row.corrected_value,
            corrected_unit=row.corrected_unit,
            original_value=row.original_value,
            original_unit=row.original_unit,
            evidence_text=row.evidence_text,
            metric_kind=kind,
        )
        if val is not None:
            try:
                num = float(str(val).replace(",", ""))
            except (TypeError, ValueError):
                num = None
            return val, unit, num
    if row.depth_min and row.depth_max:
        return f"{row.depth_min}–{row.depth_max}", row.depth_unit, row.depth_min_normalized_m
    if row.depth:
        return str(row.depth), row.depth_unit, row.depth_normalized_m
    if row.original_value:
        return str(row.original_value), row.original_unit, None
    if row.coal_quality_value:
        return str(row.coal_quality_value), row.coal_quality_unit, None
    seam = _seam_label(row)
    if seam and kind in {SEAM, None}:
        return seam, None, None
    form = _formation_ok(row.geological_formation, row.evidence_text)
    if form and kind in {FORMATION, None}:
        return form, None, None
    if row.borehole_id and kind in {BOREHOLE, None}:
        return row.borehole_id, None, None
    return None, None, None


def geological_fact_to_analytics_row(
    row: GeologicalFact,
    doc: Optional[Document] = None,
) -> Optional[dict[str, Any]]:
    """One GeologicalFact → Analytics row. None if nothing structured to show."""
    if row.status == REJECTED_STATUS:
        return None
    kind = _row_metric_kind(row)
    kind = normalize_geo_metric(kind) or kind
    value, unit, numeric = _display_value(row, kind)
    # Listing-only facts (formation/seam/borehole name) are still structured evidence
    if value is None and not kind:
        return None
    if value is None and kind in {FORMATION, SEAM, BOREHOLE}:
        # Prefer explicit listing values
        if kind == FORMATION:
            value = _formation_ok(row.geological_formation, row.evidence_text)
        elif kind == SEAM:
            value = _seam_label(row)
        elif kind == BOREHOLE:
            value = row.borehole_id
    if value is None and numeric is None and not kind:
        return None

    meta = _doc_meta(doc)
    bucket = _status_bucket(row.status)
    entity = meta.get("document_name") or row.document_id
    # Prefer mine_name from document if present
    if doc and getattr(doc, "mine_name", None):
        entity = doc.mine_name

    return {
        "domain": "geological",
        "entity": entity,
        "commodity": None,  # geological facts are not production commodities
        "metric": kind or "geological_fact",
        "metric_label": geo_metric_label(kind) if kind else "Geological Fact",
        "measure": None,
        "period": None,
        "reporting_month": None,
        "value": value,
        "numeric_value": numeric,
        "unit": unit,
        "seam": _seam_label(row),
        "formation": _formation_ok(row.geological_formation, row.evidence_text),
        "borehole": row.borehole_id,
        "document_id": row.document_id,
        "document_name": meta.get("document_name"),
        "page": row.source_page,
        "fact_id": row.id,
        "evidence_text": row.evidence_text,
        "status": row.status,
        "review_bucket": bucket,
        "requires_human_verification": bucket == "review_required",
        "source": "geological_fact",
        "storage_metric": kind,
    }


def list_geological_analytics_rows(
    db: Session,
    *,
    document_ids: Optional[list[str]] = None,
    metric: Optional[str] = None,
    seam: Optional[str] = None,
    formation: Optional[str] = None,
    include_provisional: bool = True,
) -> list[dict[str, Any]]:
    """All non-rejected GeologicalFact rows as Analytics records (no RAG fabrication)."""
    want_metric = normalize_geo_metric(metric) or metric
    rows = query_geological_facts(
        db,
        document_id=document_ids[0] if document_ids and len(document_ids) == 1 else None,
        seam=seam,
        formation=formation,
        metric=want_metric,
        limit=8000,
    )
    if document_ids and len(document_ids) != 1:
        allowed = set(document_ids)
        rows = [r for r in rows if r.document_id in allowed]
    elif document_ids and len(document_ids) == 1:
        pass  # already filtered
    docs = _doc_map(db, {r.document_id for r in rows})
    out: list[dict[str, Any]] = []
    for r in rows:
        if not include_provisional and r.status not in VERIFIED_STATUSES:
            continue
        item = geological_fact_to_analytics_row(r, docs.get(r.document_id))
        if item:
            out.append(item)
    return out


def list_geological_analytics_dimensions(
    db: Session,
    *,
    document_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    rows = list_geological_analytics_rows(db, document_ids=document_ids, include_provisional=True)
    entities: set[str] = set()
    metrics: set[str] = set()
    seams: set[str] = set()
    formations: set[str] = set()
    boreholes: set[str] = set()
    statuses: set[str] = set()
    for r in rows:
        if r.get("entity"):
            entities.add(r["entity"])
        if r.get("metric"):
            metrics.add(r["metric"])
        if r.get("seam"):
            seams.add(r["seam"])
        if r.get("formation"):
            formations.add(r["formation"])
        if r.get("borehole"):
            boreholes.add(r["borehole"])
        if r.get("status"):
            statuses.add(r["status"])

    if document_ids:
        # Scoped: build lightweight doc metas only for requested IDs (avoid full DB scan)
        docs_orm = _doc_map(db, set(document_ids))
        docs = []
        for did in document_ids:
            meta = _doc_meta(docs_orm.get(did))
            docs.append(
                {
                    **meta,
                    "display_name": meta.get("document_name") or did,
                    "fact_count": sum(1 for r in rows if r.get("document_id") == did),
                }
            )
    else:
        docs = list_geological_documents(db)

    return {
        "domain": "geological",
        "entities": sorted(entities, key=lambda x: x.lower()),
        "metrics": sorted(metrics),
        "metric_labels": {m: geo_metric_label(m) for m in sorted(metrics)},
        "seams": sorted(seams, key=lambda x: x.lower()),
        "formations": sorted(formations, key=lambda x: x.lower()),
        "boreholes": sorted(boreholes, key=lambda x: x.lower()),
        "statuses": sorted(statuses),
        "commodities": [],
        "periods": [],
        "reporting_months": [],
        "measurement_types": [],
        "documents": docs,
        "fact_count": len(rows),
        "message": None if rows else NO_STRUCTURED_GEOLOGICAL,
    }


def query_geological_analytics_data(
    db: Session,
    *,
    document_ids: Optional[list[str]] = None,
    entity: Optional[str] = None,
    metric: Optional[str] = None,
    seam: Optional[str] = None,
    formation: Optional[str] = None,
) -> dict[str, Any]:
    """Document-scoped geological Analytics — structured GeologicalFact only."""
    rows = list_geological_analytics_rows(
        db,
        document_ids=document_ids,
        metric=metric,
        seam=seam,
        formation=formation,
        include_provisional=True,
    )
    if entity:
        el = entity.strip().lower()
        # Exact entity match only — never substring (CIL must not match NLCIL).
        rows = [r for r in rows if (r.get("entity") or "").strip().lower() == el]

    if not rows:
        return {
            "domain": "geological",
            "insufficient": True,
            "message": NO_STRUCTURED_GEOLOGICAL,
            "table": [],
            "items": [],
            "provenance": [],
            "trend": {"data": [], "insufficient": True, "message": NO_STRUCTURED_GEOLOGICAL, "provenance": []},
            "actual_vs_target": None,
        }

    table = []
    provenance = []
    for r in rows:
        table.append(
            {
                "period": r.get("period") or (f"p.{r['page']}" if r.get("page") is not None else "—"),
                "metric": r.get("metric_label") or r.get("metric"),
                "seam": r.get("seam"),
                "formation": r.get("formation"),
                "borehole": r.get("borehole"),
                "actual": r.get("numeric_value") if r.get("numeric_value") is not None else r.get("value"),
                "target": None,
                "unit": r.get("unit"),
                "source": r.get("document_name"),
                "page": r.get("page"),
                "document_id": r.get("document_id"),
                "fact_id": r.get("fact_id"),
                "status": r.get("status"),
                "review_bucket": r.get("review_bucket"),
                "requires_human_verification": r.get("requires_human_verification"),
                "evidence_available": bool(r.get("evidence_text") or r.get("document_id")),
                "evidence_text": r.get("evidence_text"),
            }
        )
        provenance.append(
            {
                "entity": r.get("entity"),
                "metric": r.get("metric"),
                "period": r.get("period"),
                "value": r.get("numeric_value") if r.get("numeric_value") is not None else r.get("value"),
                "unit": r.get("unit"),
                "document_id": r.get("document_id"),
                "document_name": r.get("document_name"),
                "page": r.get("page"),
                "fact_id": r.get("fact_id"),
                "status": r.get("status"),
                "evidence_text": r.get("evidence_text"),
            }
        )

    # Chart: numeric rows only, grouped by metric label (no fabrication)
    chart_points = []
    for r in rows:
        if r.get("numeric_value") is None:
            continue
        label = r.get("seam") or r.get("formation") or r.get("borehole") or (
            f"p.{r['page']}" if r.get("page") is not None else r.get("metric_label")
        )
        chart_points.append(
            {
                "year": str(label),
                "period": str(label),
                "value": r["numeric_value"],
                "unit": r.get("unit"),
                "fact_id": r.get("fact_id"),
                "document_id": r.get("document_id"),
                "document_name": r.get("document_name"),
                "page": r.get("page"),
                "status": r.get("status"),
            }
        )

    verified = sum(1 for r in rows if r.get("status") in VERIFIED_STATUSES)
    provisional = sum(1 for r in rows if r.get("status") in PROVISIONAL_STATUSES)

    return {
        "domain": "geological",
        "entity": entity,
        "metric": normalize_geo_metric(metric) or metric,
        "metric_label": geo_metric_label(normalize_geo_metric(metric) or metric) if metric else None,
        "seam": seam,
        "formation": formation,
        "insufficient": False,
        "message": None,
        "table": table,
        "items": rows,
        "provenance": provenance,
        "counts": {
            "total": len(rows),
            "verified": verified,
            "review_required": provisional,
        },
        "trend": {
            "chart_type": "bar",
            "data": chart_points,
            "provenance": provenance,
            "insufficient": len(chart_points) == 0,
            "message": (
                "Structured geological facts exist but none have numeric values for charting."
                if not chart_points
                else None
            ),
            "unit": next((p.get("unit") for p in chart_points if p.get("unit")), None),
        },
        "actual_vs_target": None,
        "llm_context": {
            "domain": "geological",
            "facts": [
                {
                    "metric": r.get("metric_label"),
                    "value": r.get("value"),
                    "unit": r.get("unit"),
                    "seam": r.get("seam"),
                    "page": r.get("page"),
                    "status": r.get("status"),
                    "source": r.get("document_name"),
                }
                for r in rows[:40]
            ],
        },
    }


def geological_document_counts(db: Session) -> dict[str, int]:
    """document_id → non-rejected GeologicalFact count (single grouped query)."""
    from sqlalchemy import func

    rows = (
        db.query(GeologicalFact.document_id, func.count(GeologicalFact.id))
        .filter(GeologicalFact.status != REJECTED_STATUS)
        .group_by(GeologicalFact.document_id)
        .all()
    )
    return {doc_id: int(cnt) for doc_id, cnt in rows if doc_id}
