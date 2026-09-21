"""Geological Explorer — browse / filter structured GeologicalFact rows.

All aggregation is evidence-grounded. No LLM involvement. No hard-coded
document names, seam codes, formation names, or numeric answers.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.geology.entities import is_plausible_formation_name, normalize_formation_name
from app.geology.metric_kinds import (
    BOREHOLE,
    BOREHOLE_DEPTH,
    COAL_QUALITY,
    FORMATION,
    FORMATION_THICKNESS,
    LITHOLOGY,
    MINIMUM_WORKABLE_SEAM_THICKNESS,
    RESERVE_QUANTITY,
    RESOURCE_QUANTITY,
    SEAM,
    SEAM_DEPTH,
    SEAM_THICKNESS,
    classify_evidence_metric_kind,
    metrics_compatible,
)
from app.geology.seam_ids import is_valid_seam_identifier, seam_display_label
from app.geology.service import geological_fact_to_dict
from app.geology.units import canonicalize_length_unit, parse_number, to_metres
from app.models import Document, FactStatus, GeologicalFact

VERIFIED_STATUSES = frozenset(
    {
        FactStatus.HIGH_CONFIDENCE.value,
        FactStatus.APPROVED.value,
        FactStatus.CORRECTED.value,
    }
)
PROVISIONAL_STATUSES = frozenset(
    {
        FactStatus.REVIEW_REQUIRED.value,
        FactStatus.EXTRACTED.value,
    }
)
REJECTED_STATUS = FactStatus.REJECTED.value

_MASS_TO_TONNES = {
    "kg": 0.001,
    "kilogram": 0.001,
    "kilograms": 0.001,
    "t": 1.0,
    "te": 1.0,
    "ton": 1.0,
    "tons": 1.0,
    "tonne": 1.0,
    "tonnes": 1.0,
    "mt": 1_000_000.0,
    "milliontonne": 1_000_000.0,
    "milliontonnes": 1_000_000.0,
}


def to_tonnes(value: float, unit: Optional[str]) -> Optional[float]:
    """Convert mass units when unambiguous. MT = million tonnes."""
    if not unit:
        return None
    key = re.sub(r"[^a-z]", "", unit.lower())
    factor = _MASS_TO_TONNES.get(key)
    if factor is None:
        return None
    return value * factor


def resource_value_from_fact(
    row: GeologicalFact,
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """Extract resource quantity from structured fields / evidence (no invention)."""
    kind = _row_metric_kind(row)
    stored = (getattr(row, "metric_kind", None) or "").lower()
    looks_resource = kind in {
        RESOURCE_QUANTITY,
        "resource",
        RESERVE_QUANTITY,
        "reserve",
    } or stored in {
        "resource",
        "resource_quantity",
        "reserve",
        "reserve_quantity",
    }

    if row.corrected_value and looks_resource:
        num = parse_number(str(row.corrected_value))
        unit = row.corrected_unit or row.original_unit
        tonnes = to_tonnes(num, unit) if num is not None else None
        return str(row.corrected_value), unit, tonnes

    if row.original_value and stored in {
        "resource",
        "resource_quantity",
        "reserve",
        "reserve_quantity",
    }:
        num = parse_number(str(row.original_value))
        unit = row.original_unit
        tonnes = to_tonnes(num, unit) if num is not None else None
        return str(row.original_value), unit, tonnes

    ev = row.evidence_text or ""
    if re.search(r"(?i)\bresources?\b|\breserves?\b", ev):
        mq = re.search(
            r"(?i)(\d+\.\d+)\s*(MT|Mt|mt|million\s*tonnes?|t|tonnes?|kg)\b",
            ev,
        )
        if mq:
            num_s = mq.group(1).replace(",", "")
            unit_raw = mq.group(2)
            unit = "MT" if re.search(r"(?i)mt|million", unit_raw) else unit_raw
            num = parse_number(num_s)
            if num is not None and num <= 0:
                return None, None, None
            tonnes = to_tonnes(num, unit) if num is not None else None
            return num_s, unit, tonnes
    return None, None, None


def is_resource_fact(row: GeologicalFact) -> bool:
    val, _, _ = resource_value_from_fact(row)
    return val is not None


# Metric filters that map to supported structured data (shown only when present)
SUPPORTED_METRIC_FILTERS = (
    RESOURCE_QUANTITY,
    RESERVE_QUANTITY,
    SEAM_THICKNESS,
    MINIMUM_WORKABLE_SEAM_THICKNESS,
    SEAM_DEPTH,
    BOREHOLE_DEPTH,
    COAL_QUALITY,
    LITHOLOGY,
    FORMATION,
    FORMATION_THICKNESS,
    SEAM,
    BOREHOLE,
    "resource",
    "reserve",
)


def _status_bucket(status: Optional[str]) -> str:
    s = (status or "").lower()
    if s in VERIFIED_STATUSES:
        return "verified"
    if s == REJECTED_STATUS:
        return "rejected"
    return "review_required"


def _apply_status_filter(q, status: Optional[str]):
    """Filter by review bucket. Default excludes rejected."""
    bucket = (status or "").strip().lower()
    if bucket in {"verified", "official"}:
        return q.filter(GeologicalFact.status.in_(list(VERIFIED_STATUSES)))
    if bucket in {"review_required", "provisional", "pending"}:
        return q.filter(GeologicalFact.status.in_(list(PROVISIONAL_STATUSES)))
    if bucket == "rejected":
        return q.filter(GeologicalFact.status == REJECTED_STATUS)
    if bucket in {"all", "any"}:
        return q
    # default: exclude rejected
    return q.filter(GeologicalFact.status != REJECTED_STATUS)


def _row_metric_kind(row: GeologicalFact) -> Optional[str]:
    stored = (getattr(row, "metric_kind", None) or "").strip().lower() or None
    if stored:
        return stored
    has_thickness = bool(row.thickness or getattr(row, "thickness_min", None))
    has_depth = bool(row.depth or getattr(row, "depth_min", None))
    return classify_evidence_metric_kind(
        text=row.evidence_text,
        seam_name=row.seam_name,
        borehole_id=row.borehole_id,
        geological_formation=row.geological_formation,
        has_thickness=has_thickness,
        has_depth=has_depth,
    )


def _formation_ok(name: Optional[str], evidence: Optional[str] = None) -> Optional[str]:
    if not name:
        return None
    if not is_plausible_formation_name(name, context=evidence):
        return None
    return normalize_formation_name(name) or name.strip()


def _seam_label(row: GeologicalFact) -> Optional[str]:
    label = seam_display_label(
        seam_name=row.seam_name,
        seam_status=getattr(row, "seam_status", None),
    )
    if label:
        return label
    if row.seam_name and is_valid_seam_identifier(row.seam_name):
        return row.seam_name
    return None


def _doc_map(db: Session, ids: set[str]) -> dict[str, Document]:
    if not ids:
        return {}
    rows = db.query(Document).filter(Document.id.in_(list(ids))).all()
    return {d.id: d for d in rows}


def _doc_meta(doc: Optional[Document]) -> dict[str, Any]:
    if not doc:
        return {"document_id": None, "document_name": None, "document_type": None}
    meta = doc.meta or {}
    classification = meta.get("g1_classification") or {}
    return {
        "document_id": doc.id,
        "document_name": doc.original_filename or doc.filename,
        "document_type": classification.get("label")
        or doc.document_category
        or "geological",
        "domain": classification.get("domain"),
    }


def query_geological_facts(
    db: Session,
    *,
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    seam: Optional[str] = None,
    borehole: Optional[str] = None,
    metric: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> list[GeologicalFact]:
    """Filter structured geological facts. Rejected excluded unless status=rejected/all."""
    q = db.query(GeologicalFact)
    q = _apply_status_filter(q, status)
    if document_id:
        q = q.filter(GeologicalFact.document_id == document_id)
    # Formation filter applied in Python (supports seam→formation association)
    if seam:
        q = q.filter(GeologicalFact.seam_name.ilike(f"%{seam}%"))
    if borehole:
        q = q.filter(GeologicalFact.borehole_id.ilike(f"%{borehole}%"))
    rows = q.order_by(GeologicalFact.source_page, GeologicalFact.created_at).limit(8000).all()

    metric_key = (metric or "").strip().lower() or None
    if metric_key:
        # Normalize aliases
        if metric_key == "resource":
            metric_key = RESOURCE_QUANTITY
        elif metric_key == "reserve":
            metric_key = RESERVE_QUANTITY
        filtered: list[GeologicalFact] = []
        for row in rows:
            kind = _row_metric_kind(row)
            # Listing-style filters
            if metric_key == FORMATION:
                if _formation_ok(row.geological_formation, row.evidence_text):
                    filtered.append(row)
                continue
            if metric_key == SEAM:
                if _seam_label(row):
                    filtered.append(row)
                continue
            if metric_key == BOREHOLE:
                if row.borehole_id:
                    filtered.append(row)
                continue
            if metric_key == LITHOLOGY:
                if row.lithology:
                    filtered.append(row)
                continue
            if metric_key == COAL_QUALITY:
                if row.coal_quality_parameter:
                    filtered.append(row)
                continue
            if metrics_compatible(metric_key, kind):
                # Extra guard: workable vs seam thickness
                if metric_key == SEAM_THICKNESS and kind == MINIMUM_WORKABLE_SEAM_THICKNESS:
                    continue
                # Resource/reserve filters require an actual quantity —
                # from metric_kind or evidence text (older extracts).
                if metric_key in {RESOURCE_QUANTITY, "resource", RESERVE_QUANTITY, "reserve"}:
                    if not is_resource_fact(row):
                        continue
                filtered.append(row)
        rows = filtered

    # Formation filter: keep rows with the formation, or seams associated with it
    # via other structured facts in the same document.
    if formation:
        form_key = formation.lower()
        assoc_q = db.query(GeologicalFact).filter(
            GeologicalFact.status != REJECTED_STATUS,
        )
        if document_id:
            assoc_q = assoc_q.filter(GeologicalFact.document_id == document_id)
        seams_in_formation: set[str] = set()
        for r in assoc_q.limit(8000).all():
            form = _formation_ok(r.geological_formation, r.evidence_text)
            if form and form_key in form.lower():
                seam_lbl = _seam_label(r)
                if seam_lbl:
                    seams_in_formation.add(seam_lbl.lower())
        kept: list[GeologicalFact] = []
        for r in rows:
            form = _formation_ok(r.geological_formation, r.evidence_text)
            if form and form_key in (r.geological_formation or "").lower():
                kept.append(r)
                continue
            seam_lbl = _seam_label(r)
            if seam_lbl and seam_lbl.lower() in seams_in_formation:
                kept.append(r)
        rows = kept

    return rows[offset : offset + limit]


def fact_to_explorer_item(
    row: GeologicalFact,
    doc: Optional[Document] = None,
) -> dict[str, Any]:
    base = geological_fact_to_dict(row)
    kind = _row_metric_kind(row)
    formation = _formation_ok(row.geological_formation, row.evidence_text)
    seam = _seam_label(row)
    meta = _doc_meta(doc)
    bucket = _status_bucket(row.status)
    display_value = None
    display_unit = None
    if row.corrected_value:
        display_value = row.corrected_value
        display_unit = row.corrected_unit or row.original_unit
    elif row.original_value:
        display_value = row.original_value
        display_unit = row.original_unit
    elif row.thickness_min and row.thickness_max:
        display_value = f"{row.thickness_min}–{row.thickness_max}"
        display_unit = row.thickness_unit
    elif row.thickness:
        display_value = str(row.thickness)
        display_unit = row.thickness_unit
    elif row.depth_min and row.depth_max:
        display_value = f"{row.depth_min}–{row.depth_max}"
        display_unit = row.depth_unit
    elif row.depth:
        display_value = str(row.depth)
        display_unit = row.depth_unit
    elif formation:
        display_value = formation
    elif seam:
        display_value = seam
    elif row.borehole_id:
        display_value = row.borehole_id

    return {
        **base,
        "document_id": row.document_id,
        "document_name": meta["document_name"],
        "document_type": meta["document_type"],
        "metric_kind": kind,
        "formation_name": formation,
        "seam_label": seam,
        "display_value": display_value,
        "display_unit": display_unit,
        "review_bucket": bucket,
        "requires_human_verification": bucket == "review_required",
        "provenance": {
            "document_id": row.document_id,
            "document_name": meta["document_name"],
            "page": row.source_page,
            "source_location": row.source_location,
            "evidence_text": row.evidence_text,
            "status": row.status,
            "confidence": row.extraction_confidence,
        },
    }


def list_geological_documents(db: Session) -> list[dict[str, Any]]:
    """Documents that have at least one non-rejected geological fact."""
    rows = (
        db.query(GeologicalFact.document_id)
        .filter(GeologicalFact.status != REJECTED_STATUS)
        .distinct()
        .all()
    )
    ids = [r[0] for r in rows if r[0]]
    docs = _doc_map(db, set(ids))
    items = []
    for did in ids:
        doc = docs.get(did)
        summary = document_summary(db, did)
        items.append({**_doc_meta(doc), **summary})
    items.sort(key=lambda x: (x.get("document_name") or "").lower())
    return items


def document_summary(db: Session, document_id: str) -> dict[str, Any]:
    """Counts derived only from structured GeologicalFact rows."""
    rows = (
        db.query(GeologicalFact)
        .filter(
            GeologicalFact.document_id == document_id,
            GeologicalFact.status != REJECTED_STATUS,
        )
        .all()
    )
    formations: set[str] = set()
    seams: set[str] = set()
    boreholes: set[str] = set()
    resource_count = 0
    review_required = 0
    for row in rows:
        if row.status in PROVISIONAL_STATUSES or row.status == FactStatus.REVIEW_REQUIRED.value:
            review_required += 1
        form = _formation_ok(row.geological_formation, row.evidence_text)
        if form:
            formations.add(form)
        seam = _seam_label(row)
        if seam:
            seams.add(seam)
        if row.borehole_id:
            boreholes.add(row.borehole_id)
        kind = _row_metric_kind(row)
        if is_resource_fact(row):
            resource_count += 1
        elif kind in {RESOURCE_QUANTITY, "resource", RESERVE_QUANTITY, "reserve"}:
            resource_count += 1
        elif (
            getattr(row, "original_value", None)
            and (getattr(row, "metric_kind", None) or "").lower()
            in {"resource", "resource_quantity", "reserve", "reserve_quantity"}
        ):
            resource_count += 1

    doc = db.get(Document, document_id)
    meta = _doc_meta(doc)
    return {
        **meta,
        "fact_count": len(rows),
        "formation_count": len(formations),
        "seam_count": len(seams),
        "borehole_count": len(boreholes),
        "resource_fact_count": resource_count,
        "review_required_count": review_required,
        "pending_verification": review_required > 0 and not any(
            r.status in VERIFIED_STATUSES for r in rows
        ),
    }


def list_formations(
    db: Session,
    *,
    document_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows = query_geological_facts(db, document_id=document_id, status=status, limit=8000)
    by_name: dict[str, dict[str, Any]] = {}
    docs = _doc_map(db, {r.document_id for r in rows})
    for row in rows:
        name = _formation_ok(row.geological_formation, row.evidence_text)
        if not name:
            continue
        entry = by_name.setdefault(
            name,
            {
                "formation_name": name,
                "associated_seams": set(),
                "source_pages": set(),
                "evidence_count": 0,
                "statuses": set(),
                "fact_ids": [],
                "document_ids": set(),
            },
        )
        entry["evidence_count"] += 1
        entry["statuses"].add(row.status)
        entry["fact_ids"].append(row.id)
        entry["document_ids"].add(row.document_id)
        if row.source_page is not None:
            entry["source_pages"].add(row.source_page)
        seam = _seam_label(row)
        if seam:
            entry["associated_seams"].add(seam)

    out = []
    for name, entry in sorted(by_name.items(), key=lambda x: x[0].lower()):
        statuses = entry["statuses"]
        bucket = "verified" if statuses & VERIFIED_STATUSES else "review_required"
        if statuses <= {REJECTED_STATUS}:
            bucket = "rejected"
        doc_names = [
            (_doc_meta(docs.get(d)).get("document_name") or d) for d in entry["document_ids"]
        ]
        out.append(
            {
                "formation_name": name,
                "associated_seams": sorted(entry["associated_seams"]),
                "source_pages": sorted(entry["source_pages"]),
                "evidence_count": entry["evidence_count"],
                "review_status": bucket,
                "statuses": sorted(statuses),
                "requires_human_verification": bucket == "review_required",
                "fact_ids": entry["fact_ids"],
                "documents": doc_names,
            }
        )
    return out


def list_seams(
    db: Session,
    *,
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows = query_geological_facts(
        db,
        document_id=document_id,
        formation=formation,
        status=status,
        limit=8000,
    )
    by_key: dict[str, dict[str, Any]] = {}
    docs = _doc_map(db, {r.document_id for r in rows})
    for row in rows:
        seam = _seam_label(row)
        if not seam:
            continue
        key = f"{row.document_id}::{seam.lower()}"
        entry = by_key.setdefault(
            key,
            {
                "seam_name": seam,
                "seam_status": getattr(row, "seam_status", None),
                "formation": None,
                "thickness": None,
                "thickness_unit": None,
                "depth": None,
                "depth_unit": None,
                "resource": None,
                "resource_unit": None,
                "boreholes": set(),
                "source_pages": set(),
                "statuses": set(),
                "fact_ids": [],
                "document_id": row.document_id,
                "document_name": _doc_meta(docs.get(row.document_id)).get("document_name"),
                "evidence": [],
            },
        )
        entry["statuses"].add(row.status)
        entry["fact_ids"].append(row.id)
        if row.source_page is not None:
            entry["source_pages"].add(row.source_page)
        form = _formation_ok(row.geological_formation, row.evidence_text)
        if form and not entry["formation"]:
            entry["formation"] = form
        if row.borehole_id:
            entry["boreholes"].add(row.borehole_id)

        kind = _row_metric_kind(row)
        # Thickness: only compatible seam_thickness
        if (
            entry["thickness"] is None
            and metrics_compatible(SEAM_THICKNESS, kind)
            and kind == SEAM_THICKNESS
        ):
            if row.thickness_min and row.thickness_max:
                entry["thickness"] = f"{row.thickness_min}–{row.thickness_max}"
            elif row.thickness:
                entry["thickness"] = str(row.thickness)
            entry["thickness_unit"] = row.thickness_unit
        # Depth: only seam_depth
        if entry["depth"] is None and kind == SEAM_DEPTH:
            if row.depth_min and row.depth_max:
                entry["depth"] = f"{row.depth_min}–{row.depth_max}"
            elif row.depth:
                entry["depth"] = str(row.depth)
            entry["depth_unit"] = row.depth_unit
        # Resource — structured metric_kind or evidence quantity
        if entry["resource"] is None:
            rval, runit, _ = resource_value_from_fact(row)
            if rval is not None:
                entry["resource"] = rval
                entry["resource_unit"] = runit
            elif kind in {
                RESOURCE_QUANTITY,
                "resource",
                RESERVE_QUANTITY,
                "reserve",
            }:
                if row.original_value:
                    entry["resource"] = str(row.original_value)
                    entry["resource_unit"] = row.original_unit
                elif row.corrected_value:
                    entry["resource"] = str(row.corrected_value)
                    entry["resource_unit"] = row.corrected_unit

        entry["evidence"].append(
            {
                "fact_id": row.id,
                "metric_kind": kind,
                "page": row.source_page,
                "status": row.status,
                "evidence_text": (row.evidence_text or "")[:400],
            }
        )

    out = []
    for entry in sorted(by_key.values(), key=lambda x: (x["seam_name"] or "").lower()):
        statuses = entry["statuses"]
        bucket = "verified" if statuses & VERIFIED_STATUSES else "review_required"
        out.append(
            {
                "seam_name": entry["seam_name"],
                "seam_status": entry["seam_status"],
                "formation": entry["formation"],
                "thickness": entry["thickness"],
                "thickness_unit": entry["thickness_unit"],
                "depth": entry["depth"],
                "depth_unit": entry["depth_unit"],
                "resource": entry["resource"],
                "resource_unit": entry["resource_unit"],
                "boreholes": sorted(entry["boreholes"]),
                "source_pages": sorted(entry["source_pages"]),
                "review_status": bucket,
                "requires_human_verification": bucket == "review_required",
                "fact_ids": entry["fact_ids"],
                "document_id": entry["document_id"],
                "document_name": entry["document_name"],
                "evidence": entry["evidence"][:20],
            }
        )
    return out


def list_boreholes(
    db: Session,
    *,
    document_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows = query_geological_facts(db, document_id=document_id, status=status, limit=8000)
    by_key: dict[str, dict[str, Any]] = {}
    docs = _doc_map(db, {r.document_id for r in rows})
    for row in rows:
        if not row.borehole_id:
            continue
        key = f"{row.document_id}::{row.borehole_id.upper()}"
        entry = by_key.setdefault(
            key,
            {
                "borehole_id": row.borehole_id,
                "depth": None,
                "depth_unit": None,
                "depth_metric_kind": None,
                "associated_seams": set(),
                "formations": set(),
                "source_pages": set(),
                "statuses": set(),
                "fact_ids": [],
                "document_id": row.document_id,
                "document_name": _doc_meta(docs.get(row.document_id)).get("document_name"),
            },
        )
        entry["statuses"].add(row.status)
        entry["fact_ids"].append(row.id)
        if row.source_page is not None:
            entry["source_pages"].add(row.source_page)
        seam = _seam_label(row)
        if seam:
            entry["associated_seams"].add(seam)
        form = _formation_ok(row.geological_formation, row.evidence_text)
        if form:
            entry["formations"].add(form)
        kind = _row_metric_kind(row)
        # Only borehole_depth (not seam depth / formation depth)
        if entry["depth"] is None and kind == BOREHOLE_DEPTH:
            if row.depth_min and row.depth_max:
                entry["depth"] = f"{row.depth_min}–{row.depth_max}"
            elif row.depth:
                entry["depth"] = str(row.depth)
            entry["depth_unit"] = row.depth_unit
            entry["depth_metric_kind"] = kind

    out = []
    for entry in sorted(by_key.values(), key=lambda x: (x["borehole_id"] or "").lower()):
        statuses = entry["statuses"]
        bucket = "verified" if statuses & VERIFIED_STATUSES else "review_required"
        out.append(
            {
                "borehole_id": entry["borehole_id"],
                "depth": entry["depth"],
                "depth_unit": entry["depth_unit"],
                "depth_metric_kind": entry["depth_metric_kind"],
                "associated_seams": sorted(entry["associated_seams"]),
                "formations": sorted(entry["formations"]),
                "source_pages": sorted(entry["source_pages"]),
                "review_status": bucket,
                "requires_human_verification": bucket == "review_required",
                "fact_ids": entry["fact_ids"],
                "document_id": entry["document_id"],
                "document_name": entry["document_name"],
            }
        )
    return out


def get_fact_detail(db: Session, fact_id: str) -> Optional[dict[str, Any]]:
    row = db.get(GeologicalFact, fact_id)
    if not row:
        return None
    doc = db.get(Document, row.document_id)
    item = fact_to_explorer_item(row, doc)
    item["requires_human_verification"] = _status_bucket(row.status) == "review_required"
    if item["requires_human_verification"]:
        item["verification_message"] = "Requires human verification"
    return item


def filter_dimensions(
    db: Session,
    *,
    document_id: Optional[str] = None,
) -> dict[str, Any]:
    """Return only filters that correspond to actual supported data."""
    rows = query_geological_facts(db, document_id=document_id, status=None, limit=8000)
    docs = list_geological_documents(db)
    formations: set[str] = set()
    seams: set[str] = set()
    boreholes: set[str] = set()
    metrics: set[str] = set()
    statuses: set[str] = set()
    for row in rows:
        statuses.add(_status_bucket(row.status))
        form = _formation_ok(row.geological_formation, row.evidence_text)
        if form:
            formations.add(form)
            metrics.add(FORMATION)
        seam = _seam_label(row)
        if seam:
            seams.add(seam)
            metrics.add(SEAM)
        if row.borehole_id:
            boreholes.add(row.borehole_id)
            metrics.add(BOREHOLE)
        kind = _row_metric_kind(row)
        if kind:
            # Map resource aliases to canonical filter labels
            if kind in {"resource", RESOURCE_QUANTITY}:
                metrics.add("resource")
            elif kind in {"reserve", RESERVE_QUANTITY}:
                metrics.add("reserve")
            elif kind in SUPPORTED_METRIC_FILTERS:
                metrics.add(kind)
        if row.lithology:
            metrics.add(LITHOLOGY)
        if row.coal_quality_parameter:
            metrics.add(COAL_QUALITY)

    return {
        "documents": docs,
        "formations": sorted(formations),
        "seams": sorted(seams),
        "boreholes": sorted(boreholes),
        "metrics": sorted(m for m in metrics if m),
        "statuses": sorted(statuses),
    }


def explorer_overview(
    db: Session,
    *,
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    seam: Optional[str] = None,
    borehole: Optional[str] = None,
    metric: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """Combined explorer payload: summary + facts + entity lists."""
    facts = query_geological_facts(
        db,
        document_id=document_id,
        formation=formation,
        seam=seam,
        borehole=borehole,
        metric=metric,
        status=status,
        limit=500,
    )
    docs = _doc_map(db, {r.document_id for r in facts})
    items = [fact_to_explorer_item(r, docs.get(r.document_id)) for r in facts]

    summary: dict[str, Any]
    if document_id:
        summary = document_summary(db, document_id)
    else:
        all_docs = list_geological_documents(db)
        summary = {
            "document_id": None,
            "document_name": "All geological documents",
            "document_type": "geological",
            "fact_count": sum(d.get("fact_count") or 0 for d in all_docs),
            "formation_count": sum(d.get("formation_count") or 0 for d in all_docs),
            "seam_count": sum(d.get("seam_count") or 0 for d in all_docs),
            "borehole_count": sum(d.get("borehole_count") or 0 for d in all_docs),
            "resource_fact_count": sum(d.get("resource_fact_count") or 0 for d in all_docs),
            "review_required_count": sum(d.get("review_required_count") or 0 for d in all_docs),
            "documents_represented": len(all_docs),
            "pending_verification": any(d.get("pending_verification") for d in all_docs),
        }

    return {
        "summary": summary,
        "filters": filter_dimensions(db, document_id=document_id),
        "facts": {"total": len(items), "items": items},
        "formations": list_formations(db, document_id=document_id, status=status),
        "seams": list_seams(
            db, document_id=document_id, formation=formation, status=status
        ),
        "boreholes": list_boreholes(db, document_id=document_id, status=status),
    }
