"""Retrieve GeologicalFact rows for geological assistant queries.

Verification policy:
- verified_only=True → high_confidence / approved / corrected only
- verified_only=False → also include review_required / extracted as *unverified*
  evidence (status preserved; never silently promoted to verified)
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.assistant.document_resolver import resolve_documents_for_entity
from app.assistant.query_router import QueryPlan
from app.assistant.structured_retriever import StructuredFactHit, _entity_soft_match
from app.models import Document, FactStatus, GeologicalFact

VERIFIED_GEO_STATUSES = {
    FactStatus.HIGH_CONFIDENCE.value,
    FactStatus.APPROVED.value,
    FactStatus.CORRECTED.value,
}

UNVERIFIED_GEO_STATUSES = {
    FactStatus.REVIEW_REQUIRED.value,
    FactStatus.EXTRACTED.value,
}

# Seam-name noise from rule extractor (generic English leftovers — not document-specific)
from app.geology.seam_ids import is_valid_seam_identifier as plausible_seam_name  # noqa: F401


def _metric_field_filters(metric: Optional[str]) -> dict:
    m = (metric or "").lower()
    if m == "seam":
        return {"seam_name": True}
    if m in {"seam_thickness", "seam_depth"}:
        return {"measure": True, "require_seam": True}
    if m == "minimum_workable_seam_thickness":
        return {"measure_thickness": True, "workable": True}
    if m == "formation_thickness":
        return {"measure_thickness": True, "geological_formation": True, "no_seam": True}
    if m == "seam_parting_thickness":
        return {"measure_thickness": True, "parting": True}
    if m == "borehole_depth":
        return {"measure_depth": True, "borehole_id": True}
    if m == "overburden_thickness":
        return {"measure_thickness": True, "overburden": True}
    if m == "borehole":
        return {"borehole_id": True}
    if m == "lithology":
        return {"lithology": True}
    if m == "formation":
        return {"geological_formation": True}
    if m == "geological_structure":
        return {"geological_structure": True}
    if m == "coal_quality":
        return {"coal_quality_parameter": True}
    if m in {"resource", "reserve", "resource_quantity", "reserve_quantity"}:
        return {"resource_or_reserve": True, "require_seam": False}
    return {}


def _fact_value(
    row: GeologicalFact, metric: Optional[str]
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    m = (metric or "").lower()
    if m in {"seam_thickness", "formation_thickness", "seam_parting_thickness", "overburden_thickness", "minimum_workable_seam_thickness"}:
        if getattr(row, "thickness_min", None) and getattr(row, "thickness_max", None):
            return (
                f"{row.thickness_min}–{row.thickness_max}",
                row.thickness_unit,
                row.thickness_min_normalized_m,
            )
        if row.thickness is not None:
            return str(row.thickness), row.thickness_unit, row.thickness_normalized_m
        return None, None, None
    if m in {"seam_depth", "borehole_depth"}:
        if getattr(row, "depth_min", None) and getattr(row, "depth_max", None):
            return (
                f"{row.depth_min}–{row.depth_max}",
                row.depth_unit,
                row.depth_min_normalized_m,
            )
        if row.depth is not None:
            return str(row.depth), row.depth_unit, row.depth_normalized_m
        return None, None, None
    if m == "seam":
        from app.geology.seam_ids import seam_display_label

        label = seam_display_label(
            seam_name=row.seam_name,
            seam_status=getattr(row, "seam_status", None),
        )
        if label:
            return label, None, None
        if row.seam_name and plausible_seam_name(row.seam_name):
            return row.seam_name, None, None
        return None, None, None
    if m == "borehole" and row.borehole_id:
        return row.borehole_id, None, None
    if m == "lithology" and row.lithology:
        return row.lithology, None, None
    if m == "formation" and row.geological_formation:
        return row.geological_formation, None, None
    if m == "geological_structure" and row.geological_structure:
        return row.geological_structure, None, None
    if m == "coal_quality" and row.coal_quality_parameter:
        val = row.coal_quality_value or row.coal_quality_parameter
        return val, row.coal_quality_unit, None
    if m in {"resource", "reserve", "resource_quantity", "reserve_quantity"}:
        # Prefer an explicit quantity in evidence_text; never invent from seam labels alone.
        ev = row.evidence_text or ""
        # Require a decimal quantity + MT/tonnes near resource wording — avoids
        # capturing seam codes (R4) or grade codes (G10).
        patterns = [
            r"(?i)(?:gross\s+)?(?:inferred|indicated|measured|total)\s+"
            r"(?:coal\s+)?resources?\b[^.\d]{0,100}?"
            r"(\d+(?:[.,]\d+)?)\s*(MT|Mt|mt|million\s*tonnes?)",
            r"(?i)(\d+\.\d+)\s*(MT|Mt|mt)\s+of\s+(?:gross\s+)?"
            r"(?:inferred\s+)?(?:coal\s+)?resources?\b",
            r"(?i)(?:contributes|resource(?:s)?\s+(?:of|is|=|:)?)\s*"
            r"(\d+\.\d+)\s*(MT|Mt|mt)\b",
            r"(?i)(?:inferred|indicated|measured)\s+resource[^\n]{0,120}?"
            r"\b(?:[A-Z]{0,3}\d+[A-Z]?|[IVXLC]{1,6})\s+(\d+\.\d+)\b",
            r"(?i)(?:million\s*tonnes?|MT)\b[^\n]{0,40}?"
            r"\b(?:[A-Z]{0,3}\d+[A-Z]?|[IVXLC]{1,6})\s+(\d+\.\d+)\b",
        ]
        for pat in patterns:
            mq = re.search(pat, ev)
            if mq:
                num = mq.group(1).replace(",", "")
                unit = "MT"
                if mq.lastindex and mq.lastindex >= 2 and mq.group(2):
                    unit = (
                        mq.group(2)
                        .replace("million tonnes", "MT")
                        .replace("million tonne", "MT")
                    )
                try:
                    if float(num) <= 0:
                        continue
                except ValueError:
                    continue
                return num, unit, None
        # Fall back: first N.NN MT in evidence that also mentions resource
        if re.search(r"(?i)\bresources?\b", ev):
            mq = re.search(r"(?i)(\d+\.\d+)\s*(MT|Mt|mt)\b", ev)
            if mq:
                return mq.group(1), mq.group(2), None
        if getattr(row, "original_value", None) and (getattr(row, "metric_kind", None) or "") in {
            "resource",
            "reserve",
            "resource_quantity",
            "reserve_quantity",
        }:
            return str(row.original_value), row.original_unit or "MT", None
        return None, None, None
    if row.seam_name and plausible_seam_name(row.seam_name):
        return row.seam_name, None, None
    if row.borehole_id:
        return row.borehole_id, None, None
    if row.lithology:
        return row.lithology, None, None
    if row.geological_formation:
        return row.geological_formation, None, None
    if getattr(row, "thickness_min", None) and getattr(row, "thickness_max", None):
        return (
            f"{row.thickness_min}–{row.thickness_max}",
            row.thickness_unit,
            row.thickness_min_normalized_m,
        )
    if row.thickness is not None:
        return str(row.thickness), row.thickness_unit, row.thickness_normalized_m
    if row.depth is not None:
        return str(row.depth), row.depth_unit, row.depth_normalized_m
    return None, None, None


def _explicit_seam(question: str) -> Optional[str]:
    from app.geology.entities import extract_seam_from_question

    return extract_seam_from_question(question or "")


def _seam_key(name: Optional[str]) -> str:
    from app.geology.entities import seam_match_key

    return seam_match_key(name)


def _doc_matches_entity(doc: Document, entity: Optional[str]) -> bool:
    if not entity:
        return True
    blob = " ".join(
        filter(
            None,
            [
                doc.original_filename,
                doc.filename,
                doc.mine_name,
                (doc.meta or {}).get("title") if isinstance(doc.meta, dict) else None,
            ],
        )
    )
    if _entity_soft_match(entity, blob):
        return True
    tokens = [t for t in re.findall(r"[a-z0-9]{4,}", entity.lower())]
    low = blob.lower().replace("_", " ").replace("-", " ")
    if tokens and all(t in low for t in tokens):
        return True
    return False


def _explicit_borehole(question: str) -> Optional[str]:
    from app.geology.entities import extract_borehole_from_question

    return extract_borehole_from_question(question or "")


def _row_metric_kind(row: GeologicalFact) -> Optional[str]:
    mk = getattr(row, "metric_kind", None)
    if mk:
        return mk
    from app.geology.entities import infer_metric_kind_from_fields

    return infer_metric_kind_from_fields(
        seam_name=row.seam_name,
        borehole_id=row.borehole_id,
        geological_formation=row.geological_formation,
        lithology=row.lithology,
        geological_structure=row.geological_structure,
        coal_quality_parameter=row.coal_quality_parameter,
        has_thickness=bool(row.thickness or getattr(row, "thickness_min", None)),
        has_depth=bool(row.depth or getattr(row, "depth_min", None)),
        evidence_text=row.evidence_text,
    )


def retrieve_geological_facts(
    db: Session,
    plan: QueryPlan,
    *,
    verified_only: bool = True,
    include_unverified: bool = False,
    document_ids: Optional[list[str]] = None,
    limit: int = 40,
) -> list[StructuredFactHit]:
    """Return GeologicalFact rows as StructuredFactHit for the evidence pack."""
    if not getattr(plan, "is_geological", False):
        return []

    from app.geology.entities import (
        boreholes_match,
        formations_match,
        is_plausible_formation_name,
        seams_match,
    )
    from app.geology.metric_kinds import metrics_compatible

    q = db.query(GeologicalFact)
    if verified_only and not include_unverified:
        q = q.filter(GeologicalFact.status.in_(VERIFIED_GEO_STATUSES))
    elif include_unverified:
        allowed = VERIFIED_GEO_STATUSES | UNVERIFIED_GEO_STATUSES
        q = q.filter(GeologicalFact.status.in_(allowed))
    else:
        q = q.filter(GeologicalFact.status != FactStatus.REJECTED.value)

    resolved_ids = list(document_ids) if document_ids is not None else []
    scoped = document_ids is not None
    if not scoped and not resolved_ids and plan.entity:
        resolved_ids = [r.document_id for r in resolve_documents_for_entity(db, plan.entity)]
    if scoped or resolved_ids:
        # Empty scoped list → match nothing (do not widen to all documents)
        q = q.filter(GeologicalFact.document_id.in_(resolved_ids or ["__no_document__"]))

    metrics = list(
        getattr(plan, "geological_metrics", None)
        or plan.metrics
        or ([plan.metric] if plan.metric else [])
    )
    primary = metrics[0] if metrics else None
    field_req = _metric_field_filters(primary)
    if field_req.get("seam_name") or field_req.get("require_seam"):
        # Listing may include uncorrelated/unnamed seams without identifiers
        if primary == "seam":
            q = q.filter(
                or_(
                    GeologicalFact.seam_name.isnot(None),
                    GeologicalFact.seam_status.in_(["uncorrelated", "unnamed"]),
                )
            )
        else:
            q = q.filter(GeologicalFact.seam_name.isnot(None))
    if field_req.get("measure_thickness"):
        q = q.filter(
            or_(
                GeologicalFact.thickness.isnot(None),
                GeologicalFact.thickness_min.isnot(None),
            )
        )
    elif field_req.get("measure_depth"):
        q = q.filter(
            or_(
                GeologicalFact.depth.isnot(None),
                GeologicalFact.depth_min.isnot(None),
            )
        )
    elif field_req.get("measure"):
        q = q.filter(
            or_(
                GeologicalFact.thickness.isnot(None),
                GeologicalFact.thickness_min.isnot(None),
                GeologicalFact.depth.isnot(None),
                GeologicalFact.depth_min.isnot(None),
            )
        )
    if field_req.get("borehole_id"):
        q = q.filter(GeologicalFact.borehole_id.isnot(None))
    if field_req.get("lithology"):
        q = q.filter(GeologicalFact.lithology.isnot(None))
    if field_req.get("geological_formation"):
        q = q.filter(GeologicalFact.geological_formation.isnot(None))
    if field_req.get("geological_structure"):
        q = q.filter(GeologicalFact.geological_structure.isnot(None))
    if field_req.get("coal_quality_parameter"):
        q = q.filter(GeologicalFact.coal_quality_parameter.isnot(None))

    rows = q.order_by(GeologicalFact.source_page, GeologicalFact.created_at).limit(800).all()

    # Workable-thickness filter (metric_kind or evidence cue)
    if field_req.get("workable") or primary == "minimum_workable_seam_thickness":
        rows = [
            r
            for r in rows
            if (getattr(r, "metric_kind", None) or "") == "minimum_workable_seam_thickness"
            or re.search(r"(?i)\bworkable\b", r.evidence_text or "")
        ]
    if field_req.get("resource_or_reserve") or primary in {
        "resource",
        "reserve",
        "resource_quantity",
        "reserve_quantity",
    }:
        cue = r"\bresources?\b" if (primary or "").startswith("resource") else r"\breserves?\b"
        # Accept either resource or reserve cues; keep them distinct at value-parse time
        rows = [
            r
            for r in rows
            if re.search(r"(?i)\b(?:resource|reserve)s?\b", r.evidence_text or "")
            or (getattr(r, "metric_kind", None) or "")
            in {"resource", "reserve", "resource_quantity", "reserve_quantity"}
        ]
        if primary and primary.startswith("resource"):
            # Prefer resource wording; still allow "reserve" evidence only when no resource cue
            # but do not convert reserve→resource in the displayed metric.
            pass
        _ = cue  # reserved for future tighter filtering
    rows.sort(
        key=lambda r: (
            0 if r.status in VERIFIED_GEO_STATUSES else 1,
            -(r.extraction_confidence or 0),
            r.source_page or 0,
        )
    )

    # Prefer plan slots (G2) over re-parsing the question
    want_seams = list(getattr(plan, "geological_seams", None) or [])
    want_seam = getattr(plan, "geological_seam", None) or (
        want_seams[0] if want_seams else _explicit_seam(plan.raw_question or "")
    )
    if want_seam and want_seam not in want_seams:
        want_seams = [want_seam] + want_seams
    bh = getattr(plan, "geological_borehole", None) or _explicit_borehole(
        plan.raw_question or ""
    )
    want_formation = getattr(plan, "geological_formation", None)
    # Listing asks ("what formations…") must not treat the question word as a formation filter
    if want_formation and not is_plausible_formation_name(want_formation):
        want_formation = None
    if (
        want_formation
        and (primary or "") == "formation"
        and bool(getattr(plan, "listing_intent", False))
    ):
        # Specific named formation in a listing question is rare; only keep when
        # the name is a plausible proper formation distinct from question words.
        from app.geology.entities import formation_match_key

        if formation_match_key(want_formation) in {
            "what",
            "which",
            "where",
            "this",
            "that",
            "the",
        }:
            want_formation = None

    if bh:
        rows = [r for r in rows if r.borehole_id and boreholes_match(r.borehole_id, bh)]

    if want_seams:
        rows = [
            r
            for r in rows
            if r.seam_name and any(seams_match(r.seam_name, s) for s in want_seams)
        ]
    elif want_seam:
        rows = [r for r in rows if r.seam_name and seams_match(r.seam_name, want_seam)]

    if want_formation:
        rows = [
            r
            for r in rows
            if r.geological_formation
            and formations_match(r.geological_formation, want_formation)
        ]

    doc_cache: dict[str, Document] = {}
    hits: list[StructuredFactHit] = []
    seen: set[str] = set()

    for row in rows:
        if row.document_id not in doc_cache:
            doc_cache[row.document_id] = db.get(Document, row.document_id)
        doc = doc_cache.get(row.document_id)
        if not doc:
            continue
        if not resolved_ids and plan.entity and not _doc_matches_entity(doc, plan.entity):
            continue

        row_kind = _row_metric_kind(row)
        # Metric-kind gate: never substitute formation_thickness for seam_thickness etc.
        if primary and row_kind and not metrics_compatible(primary, row_kind):
            # Listing / quantity metrics may still match entity-associated rows
            if primary not in {
                "seam",
                "borehole",
                "lithology",
                "formation",
                "geological_structure",
                "resource",
                "reserve",
                "resource_quantity",
                "reserve_quantity",
            }:
                continue
            if primary == "seam" and row_kind not in {None, "seam", "seam_thickness", "seam_depth"}:
                if not (row.seam_name and plausible_seam_name(row.seam_name)):
                    continue
            if primary == "borehole" and not row.borehole_id:
                continue
            # resource/reserve with seam-kind rows: allowed only when metrics_compatible
            # already returned True (resource↔seam). If we are here, skip.
            if primary in {
                "resource",
                "reserve",
                "resource_quantity",
                "reserve_quantity",
            }:
                continue

        if primary in {"seam_thickness", "seam_depth"}:
            if not row.seam_name or not plausible_seam_name(row.seam_name):
                continue
            # Reject workable / methodology norms as named-seam thickness
            ev_low = (row.evidence_text or "").lower()
            if primary == "seam_thickness" and (
                row_kind == "minimum_workable_seam_thickness"
                or re.search(r"(?i)\b(?:minimum\s+)?workable\s+thickness\b", ev_low)
                or re.search(r"(?i)\bbelow\s+\d+\s*cm\s+thickness\b", ev_low)
            ):
                continue
            if primary == "seam_thickness" and not (
                row.thickness is not None or getattr(row, "thickness_min", None) is not None
            ):
                continue
            if primary == "seam_depth" and not (
                row.depth is not None or getattr(row, "depth_min", None) is not None
            ):
                continue
            # When the query names a seam, evidence must associate that seam
            if want_seam and not seams_match(row.seam_name, want_seam):
                continue
            from app.geology.metric_kinds import classify_evidence_metric_kind

            kind = row_kind or classify_evidence_metric_kind(
                text=row.evidence_text or "",
                seam_name=row.seam_name,
                borehole_id=row.borehole_id,
                geological_formation=row.geological_formation,
                has_thickness=primary == "seam_thickness",
                has_depth=primary == "seam_depth",
                requested=primary,
            )
            if not metrics_compatible(primary, kind):
                continue
        elif primary == "minimum_workable_seam_thickness":
            if not (
                row.thickness is not None or getattr(row, "thickness_min", None) is not None
            ):
                continue
            if row_kind and row_kind != "minimum_workable_seam_thickness":
                if not re.search(r"(?i)\bworkable\b", row.evidence_text or ""):
                    continue
        elif primary == "formation_thickness":
            from app.geology.metric_kinds import classify_evidence_metric_kind

            if row.seam_name and plausible_seam_name(row.seam_name):
                continue
            if (getattr(row, "seam_status", None) or "").lower() in {
                "uncorrelated",
                "unnamed",
            }:
                continue
            if not (
                row.thickness is not None or getattr(row, "thickness_min", None) is not None
            ):
                continue
            kind = row_kind or classify_evidence_metric_kind(
                text=row.evidence_text or "",
                seam_name=None,
                geological_formation=row.geological_formation,
                has_thickness=True,
                requested="formation_thickness",
            )
            if not metrics_compatible("formation_thickness", kind):
                continue
        elif primary == "seam_parting_thickness":
            ev = (row.evidence_text or "").lower()
            if "parting" not in ev and row_kind != "seam_parting_thickness":
                continue
            if not (
                row.thickness is not None or getattr(row, "thickness_min", None) is not None
            ):
                continue
        elif primary == "borehole_depth":
            if not row.borehole_id:
                continue
            if not (row.depth is not None or getattr(row, "depth_min", None) is not None):
                continue
        elif primary == "seam":
            status = (getattr(row, "seam_status", None) or "").lower()
            if status in {"uncorrelated", "unnamed"}:
                pass  # valid unnamed entity
            elif row.seam_name:
                if not plausible_seam_name(row.seam_name):
                    continue
            else:
                continue
        elif primary in {"resource", "reserve", "resource_quantity", "reserve_quantity"}:
            ev = (row.evidence_text or "").lower()
            cue = "resource" if primary.startswith("resource") else "reserve"
            kind_ok = (row_kind or "") in {
                "resource",
                "reserve",
                "resource_quantity",
                "reserve_quantity",
            }
            if cue not in ev and not kind_ok:
                continue
            # Do not answer resource asks with workable-thickness methodology rows
            if "workable" in ev and "resource" not in ev:
                continue

        value, unit, numeric = _fact_value(row, primary)
        if value is None:
            continue
        # Drop degenerate zero thickness without unit/context
        if primary == "seam_thickness" and value in {"0", "0.0", "0.00"}:
            continue

        if primary in {"seam_thickness", "seam_depth"} and row.seam_name:
            entity_label = row.seam_name
        elif primary == "seam":
            from app.geology.seam_ids import seam_display_label

            entity_label = (
                seam_display_label(
                    seam_name=row.seam_name,
                    seam_status=getattr(row, "seam_status", None),
                )
                or row.seam_name
                or plan.entity
                or doc.original_filename
                or doc.filename
            )
        elif primary == "borehole" and row.borehole_id:
            entity_label = row.borehole_id
        elif primary == "formation" and row.geological_formation:
            from app.geology.entities import is_plausible_formation_name, normalize_formation_name

            if not is_plausible_formation_name(
                row.geological_formation, context=row.evidence_text
            ):
                continue
            entity_label = (
                normalize_formation_name(row.geological_formation) or row.geological_formation
            )
            # Always expose the normalized formation name as the listed value
            value = entity_label
        elif primary == "formation_thickness" and row.geological_formation:
            from app.geology.entities import is_plausible_formation_name, normalize_formation_name

            if not is_plausible_formation_name(
                row.geological_formation, context=row.evidence_text
            ):
                continue
            entity_label = (
                normalize_formation_name(row.geological_formation) or row.geological_formation
            )
        elif primary in {"resource", "reserve", "resource_quantity", "reserve_quantity"}:
            entity_label = row.seam_name or plan.entity or doc.original_filename or doc.filename
        else:
            entity_label = plan.entity or doc.original_filename or doc.filename

        fm_for_hit = None
        if row.geological_formation:
            from app.geology.entities import is_plausible_formation_name, normalize_formation_name

            if is_plausible_formation_name(row.geological_formation, context=row.evidence_text):
                fm_for_hit = (
                    normalize_formation_name(row.geological_formation) or row.geological_formation
                )

        dedupe_key = (
            f"{row.document_id}|{primary}|{_seam_key(row.seam_name)}|"
            f"{(row.borehole_id or '').lower()}|{value}|{row.source_page}|{row.status}"
        )
        if primary == "seam":
            status = (getattr(row, "seam_status", None) or "named").lower()
            fm_key = re.sub(
                r"[^a-z0-9]+", "", (row.geological_formation or "").lower()
            )
            if status in {"uncorrelated", "unnamed"}:
                dedupe_key = f"{row.document_id}|seam|{status}|{fm_key}"
            elif row.seam_name:
                dedupe_key = f"{row.document_id}|seam|{_seam_key(row.seam_name)}"
        if primary == "borehole" and row.borehole_id:
            bh_id = row.borehole_id.strip()
            if len(bh_id) < 3 or re.fullmatch(r"\d+", bh_id):
                continue
            dedupe_key = f"{row.document_id}|bh|{bh_id.lower()}"
        if primary == "lithology" and row.lithology:
            dedupe_key = f"{row.document_id}|lith|{row.lithology.lower()}"
        if primary == "formation" and row.geological_formation:
            from app.geology.entities import formation_match_key

            fm_key = formation_match_key(row.geological_formation)
            if not fm_key:
                continue
            # One logical formation per document (multi-page evidence collapsed)
            dedupe_key = f"{row.document_id}|fm|{fm_key}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        v_min = (
            getattr(row, "thickness_min", None)
            if primary
            in {
                "seam_thickness",
                "formation_thickness",
                "seam_parting_thickness",
                "overburden_thickness",
                "minimum_workable_seam_thickness",
            }
            else getattr(row, "depth_min", None)
        )
        v_max = (
            getattr(row, "thickness_max", None)
            if primary
            in {
                "seam_thickness",
                "formation_thickness",
                "seam_parting_thickness",
                "overburden_thickness",
                "minimum_workable_seam_thickness",
            }
            else getattr(row, "depth_max", None)
        )
        v_min_n = (
            getattr(row, "thickness_min_normalized_m", None)
            if primary
            in {
                "seam_thickness",
                "formation_thickness",
                "seam_parting_thickness",
                "overburden_thickness",
                "minimum_workable_seam_thickness",
            }
            else getattr(row, "depth_min_normalized_m", None)
        )
        v_max_n = (
            getattr(row, "thickness_max_normalized_m", None)
            if primary
            in {
                "seam_thickness",
                "formation_thickness",
                "seam_parting_thickness",
                "overburden_thickness",
                "minimum_workable_seam_thickness",
            }
            else getattr(row, "depth_max_normalized_m", None)
        )

        # Enrich listing value with formation when present
        display_value = value
        if primary == "seam" and fm_for_hit:
            display_value = f"{value} — {fm_for_hit}"

        hits.append(
            StructuredFactHit(
                entity=entity_label,
                metric=primary or row_kind or "geological_fact",
                period=None,
                value=display_value,
                numeric_value=numeric,
                unit=unit,
                status=row.status,
                document_id=row.document_id,
                document_name=doc.original_filename or doc.filename,
                document_version=doc.version or 1,
                page=row.source_page,
                sheet_name=None,
                evidence_text=row.evidence_text,
                fact_id=row.id,
                confidence=float(row.extraction_confidence or 0.0),
                seam_name=row.seam_name if plausible_seam_name(row.seam_name) else None,
                borehole_id=row.borehole_id,
                geological_formation=fm_for_hit,
                seam_status=getattr(row, "seam_status", None),
                value_min=v_min,
                value_max=v_max,
                value_min_normalized=v_min_n,
                value_max_normalized=v_max_n,
            )
        )
        if len(hits) >= limit:
            break

    hits = prefer_multi_seam_thickness(
        hits, plan, want_seam=want_seam if len(want_seams) <= 1 else None, primary=primary
    )
    return hits


def prefer_multi_seam_thickness(
    hits: list[StructuredFactHit],
    plan: QueryPlan,
    *,
    want_seam: Optional[str] = None,
    primary: Optional[str] = None,
) -> list[StructuredFactHit]:
    """For multi-seam thickness asks, keep one best fact per seam (prefer verified ranges).

    Also collapses formation listing hits to one logical formation per document.
    """
    primary = primary or (
        (getattr(plan, "geological_metrics", None) or plan.metrics or [None])[0]
    )
    if want_seam is None:
        want_seam = _explicit_seam(plan.raw_question or "")

    if primary == "formation" and hits:
        from app.geology.entities import formation_match_key

        best: dict[str, StructuredFactHit] = {}
        for h in hits:
            key = f"{h.document_id}|{formation_match_key(h.value or h.geological_formation)}"
            if not formation_match_key(h.value or h.geological_formation):
                continue
            cur = best.get(key)
            if cur is None or (h.confidence or 0) > (cur.confidence or 0):
                best[key] = h
        return list(best.values())

    if primary != "seam_thickness" or want_seam or not hits:
        return hits

    def _rank(h: StructuredFactHit) -> tuple:
        is_range = 1 if (h.value_min and h.value_max) else 0
        verified = 1 if h.status in VERIFIED_GEO_STATUSES else 0
        degenerated = 1 if (h.value or "") in {"0", "0.0", "0.00"} else 0
        return (is_range, verified, -degenerated, h.confidence or 0)

    best: dict[str, StructuredFactHit] = {}
    for h in hits:
        sk = _seam_key(h.seam_name)
        if not sk:
            continue
        if (h.value or "") in {"0", "0.0", "0.00"} and not (h.value_min and h.value_max):
            continue
        cur = best.get(sk)
        if cur is None or _rank(h) > _rank(cur):
            best[sk] = h
    return list(best.values()) or hits


def geological_structured_available(db: Session, plan: QueryPlan) -> bool:
    """True if any usable geo facts exist (verified preferred; unverified counts for hybrid)."""
    if retrieve_geological_facts(db, plan, verified_only=True, limit=1):
        return True
    return bool(
        retrieve_geological_facts(
            db, plan, verified_only=False, include_unverified=True, limit=1
        )
    )


def detect_geological_conflicts(
    hits: list[StructuredFactHit],
) -> list[dict]:
    """Detect geological conflicts / cross-document discrepancies (G3).

    Same-document mismatches → geological_value_mismatch.
    Cross-document disagreements → cross_document_discrepancy (not auto-contradiction).
    Different seams/metrics/formations are never conflicts.
    """
    from app.geology.validation import conflicts_as_dicts

    return conflicts_as_dicts(hits, allow_cross_document=True)
