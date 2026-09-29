"""Phase 6 analytics — verified structured facts only (no LLM-invented numbers)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.analytics.dimensions import (
    classify_raw_metric,
    commodity_label,
    measure_label,
    normalize_commodity,
    normalize_measure_param,
    storage_metrics_for,
)
from app.analytics.index_facts import (
    _is_plausible_entity,
    index_facts_as_hits,
    list_analytics_documents,
    list_index_facts,
)
from app.assistant.structured_retriever import (
    StructuredFactHit,
    conflicts_for_structured,
    retrieve_structured_facts,
)
from app.models import Document, ExtractedFact, FactStatus
from app.validation.rules import normalize_field, normalize_period

VERIFIED = {
    FactStatus.HIGH_CONFIDENCE.value,
    FactStatus.APPROVED.value,
    FactStatus.CORRECTED.value,
}


def _merge_hits(
    db: Session,
    *,
    entity: Optional[str],
    metric: Optional[str],
    periods: Optional[list[str]] = None,
    document_ids: Optional[list[str]] = None,
    reporting_month: Optional[str] = None,
    measurement_type: Optional[str] = None,
    metrics: Optional[list[str]] = None,
) -> list[StructuredFactHit]:
    """Prefer indexed STRUCTURED_FACT chunks; also include verified ExtractedFact rows."""
    metric_list = [m for m in (metrics or ([metric] if metric else [])) if m]
    if not metric_list and metric:
        metric_list = [metric]

    merged: list[StructuredFactHit] = []
    seen: set[tuple] = set()

    def _add(h: StructuredFactHit) -> None:
        key = (
            (h.entity or "").lower(),
            h.metric,
            h.period,
            round(float(h.numeric_value), 6) if h.numeric_value is not None else None,
            (getattr(h, "measurement_type", None) or ""),
        )
        if key in seen:
            return
        seen.add(key)
        merged.append(h)

    for m in metric_list or [None]:
        index_rows = list_index_facts(
            db,
            document_ids=document_ids,
            entity=entity,
            metric=m,
            fiscal_year=periods[0] if periods and len(periods) == 1 else None,
            reporting_month=reporting_month,
            measurement_type=measurement_type,
        )
        if periods and len(periods) > 1:
            want = {normalize_period(p) for p in periods if normalize_period(p)}
            index_rows = [r for r in index_rows if r.fiscal_year in want]

        for h in index_facts_as_hits(index_rows):
            _add(h)

        extracted = retrieve_structured_facts(
            db,
            entity=entity,
            metric=m,
            periods=periods,
            verified_only=True,
        )
        if document_ids:
            allowed = set(document_ids)
            extracted = [h for h in extracted if h.document_id in allowed]
        # ExtractedFact path has no measurement_type; skip when caller wants target-only
        # via measurement_type unless metric itself is a target field.
        meas = (measurement_type or "").strip().lower() or None
        for h in extracted:
            if meas == "target" and (normalize_field(h.metric) or h.metric) not in {
                "production_target",
            }:
                continue
            if meas in {"during", "actual", "upto"} and (
                normalize_field(h.metric) or h.metric
            ) == "production_target":
                continue
            _add(h)

    return merged


def _classified_fact_rows(
    db: Session,
    *,
    document_ids: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Flatten index + ExtractedFact rows with semantic commodity/metric/measure."""
    rows: list[dict[str, Any]] = []
    for f in list_index_facts(db, document_ids=document_ids, limit=10000):
        if not _is_plausible_entity(f.entity):
            continue
        cls = classify_raw_metric(f.metric, measurement_type=f.measurement_type)
        rows.append(
            {
                "entity": f.entity,
                "commodity": cls["commodity"],
                "metric": cls["metric"],
                "measure": cls["measure"],
                "storage_metric": cls["storage_metric"] or f.metric,
                "period": f.fiscal_year,
                "reporting_month": f.reporting_month,
                "value": f.value,
                "unit": f.unit,
                "document_id": f.document_id,
                "document_name": f.document_name,
                "page": f.page,
                "fact_id": f.chunk_id,
                "evidence_text": f.evidence_text,
                "status": "verified_index",
                "source": "index",
            }
        )

    q = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.status.in_(VERIFIED))
        .filter(ExtractedFact.is_calculated.is_(False))
        .filter(ExtractedFact.numeric_value.isnot(None))
    )
    if document_ids:
        q = q.filter(ExtractedFact.document_id.in_(document_ids))
    docs = {d.id: d for d in db.query(Document).all()}
    for f in q.all():
        if not f.entity_name or not _is_plausible_entity(f.entity_name):
            continue
        cls = classify_raw_metric(f.field_name, measurement_type=None)
        doc = docs.get(f.document_id)
        rows.append(
            {
                "entity": f.entity_name,
                "commodity": cls["commodity"],
                "metric": cls["metric"],
                "measure": cls["measure"],
                "storage_metric": cls["storage_metric"] or f.field_name,
                "period": normalize_period(f.financial_year),
                "reporting_month": None,
                "value": float(f.numeric_value) if f.numeric_value is not None else None,
                "unit": f.unit,
                "document_id": f.document_id,
                "document_name": (doc.original_filename or doc.filename) if doc else f.document_id,
                "page": f.page_number,
                "fact_id": f.id,
                "evidence_text": f.evidence_text,
                "status": f.status,
                "source": "extracted",
            }
        )
    return rows


@dataclass
class ProvenancePoint:
    entity: str
    metric: str
    period: Optional[str]
    value: float
    unit: Optional[str]
    document_id: str
    document_name: str
    page: Optional[int]
    sheet_name: Optional[str]
    fact_id: str
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "metric": self.metric,
            "period": self.period,
            "value": self.value,
            "unit": self.unit,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "page": self.page,
            "sheet_name": self.sheet_name,
            "fact_id": self.fact_id,
            "status": self.status,
        }


def _hit_to_prov(h: StructuredFactHit) -> ProvenancePoint:
    return ProvenancePoint(
        entity=h.entity,
        metric=h.metric,
        period=h.period,
        value=float(h.numeric_value) if h.numeric_value is not None else 0.0,
        unit=h.unit,
        document_id=h.document_id,
        document_name=h.document_name,
        page=h.page,
        sheet_name=h.sheet_name,
        fact_id=h.fact_id,
        status=h.status,
    )


def _has_open_conflict(
    db: Session, *, entity: Optional[str], metric: Optional[str], periods: Optional[list[str]]
) -> bool:
    return bool(conflicts_for_structured(db, entity=entity, metric=metric, periods=periods))


def _resolve_analytics_domain(
    db: Session,
    *,
    domain: Optional[str] = None,
    document_ids: Optional[list[str]] = None,
) -> str:
    """Return 'geological' | 'production' | 'mixed'. Explicit domain wins."""
    explicit = (domain or "").strip().lower()
    if explicit in {"geological", "geology", "geo", "exploration"}:
        return "geological"
    if explicit in {"production", "mining"}:
        return "production"

    docs = list_analytics_documents(db)
    if document_ids:
        allowed = set(document_ids)
        docs = [d for d in docs if d["id"] in allowed]
    geo = sum(int(d.get("geological_fact_count") or 0) for d in docs)
    prod = sum(int(d.get("production_fact_count") or 0) for d in docs)
    if geo and not prod:
        return "geological"
    if prod and not geo:
        return "production"
    if geo and prod:
        # Document-scoped mix: prefer geological only when every selected doc is geo-only
        if document_ids and all(
            (d.get("domain") == "geological") for d in docs if d.get("has_structured_data")
        ):
            return "geological"
        return "mixed"
    return "production"


def list_dimensions(
    db: Session,
    *,
    document_ids: Optional[list[str]] = None,
    entity: Optional[str] = None,
    commodity: Optional[str] = None,
    metric: Optional[str] = None,
    domain: Optional[str] = None,
) -> dict[str, Any]:
    """Entities / commodities / metrics / measures / periods from structured data.

    Dependent filters (optional):
      entity → commodities/metrics/periods for that entity
      commodity → metrics/periods for that commodity
      metric → periods for that metric

    When domain resolves to geological, expose GeologicalFact-backed dimensions
    (no production FY/target filters).
    """
    resolved = _resolve_analytics_domain(db, domain=domain, document_ids=document_ids)
    if resolved == "geological":
        from app.analytics.geological_adapter import list_geological_analytics_dimensions

        geo = list_geological_analytics_dimensions(db, document_ids=document_ids)
        # Map geological docs into Analytics document shape
        docs = list_analytics_documents(db)
        if document_ids:
            allowed = set(document_ids)
            docs = [d for d in docs if d["id"] in allowed]
        else:
            docs = [d for d in docs if int(d.get("geological_fact_count") or 0) > 0]
        metric_labels = geo.get("metric_labels") or {}
        return {
            "domain": "geological",
            "entities": geo.get("entities") or [],
            "commodities": [],
            "commodity_labels": {},
            "metrics": geo.get("metrics") or [],
            "semantic_metrics": geo.get("metrics") or [],
            "metric_labels": metric_labels,
            "periods": [],
            "reporting_months": [],
            "measurement_types": [],
            "measure_labels": {},
            "seams": geo.get("seams") or [],
            "formations": geo.get("formations") or [],
            "boreholes": geo.get("boreholes") or [],
            "statuses": geo.get("statuses") or [],
            "documents": docs,
            "suggested_entity": (geo.get("entities") or [None])[0],
            "suggested_metric": (geo.get("metrics") or [None])[0],
            "suggested_commodity": None,
            "suggested_reporting_month": None,
            "entity_fact_scores": {},
            "fact_count": geo.get("fact_count") or 0,
            "message": geo.get("message"),
            "filters_applied": {
                "entity": entity,
                "commodity": None,
                "metric": metric,
                "domain": "geological",
            },
        }

    all_rows = _classified_fact_rows(db, document_ids=document_ids)
    want_commodity = normalize_commodity(commodity)
    want_metric = (normalize_field(metric) or (metric or "").strip().lower()) or None
    want_entity = (entity or "").strip() or None

    entities: set[str] = set()
    commodities: set[str] = set()
    semantic_metrics: set[str] = set()
    raw_metrics: set[str] = set()
    measures: set[str] = set()
    periods: set[str] = set()
    months: set[str] = set()
    ent_scores: dict[str, int] = defaultdict(int)

    # Unfiltered entity list + scores
    for r in all_rows:
        entities.add(r["entity"])
        sm = r["storage_metric"] or ""
        weight = 3 if sm in {"production", "coal", "overburden", "dispatch", "lignite"} else 1
        ent_scores[r["entity"]] += weight
        if r.get("storage_metric"):
            raw_metrics.add(r["storage_metric"])

    # Apply dependent filters for dimension values
    filtered = all_rows
    if want_entity:
        filtered = [
            r
            for r in filtered
            if (r["entity"] or "").lower() == want_entity.lower()
        ]
    if want_commodity:
        filtered = [r for r in filtered if r.get("commodity") == want_commodity]
    if want_metric:
        # Accept legacy commodity-as-metric in the metric filter
        filtered = [
            r
            for r in filtered
            if r.get("metric") == want_metric or r.get("storage_metric") == want_metric
        ]

    for r in filtered:
        if r.get("commodity"):
            commodities.add(r["commodity"])
        if r.get("metric"):
            semantic_metrics.add(r["metric"])
        if r.get("measure"):
            measures.add(r["measure"])
        if r.get("period"):
            periods.add(r["period"])
        if r.get("reporting_month"):
            months.add(r["reporting_month"])

    # When no entity filter: still expose all commodities/metrics from full set
    if not want_entity and not want_commodity and not want_metric:
        for r in all_rows:
            if r.get("commodity"):
                commodities.add(r["commodity"])
            if r.get("metric"):
                semantic_metrics.add(r["metric"])
            if r.get("measure"):
                measures.add(r["measure"])
            if r.get("period"):
                periods.add(r["period"])
            if r.get("reporting_month"):
                months.add(r["reporting_month"])

    docs = list_analytics_documents(db)
    if document_ids:
        allowed = set(document_ids)
        docs = [d for d in docs if d["id"] in allowed]

    suggested_entity = None
    if ent_scores:
        suggested_entity = max(ent_scores.items(), key=lambda kv: (kv[1], -len(kv[0])))[0]

    # Prefer production as suggested semantic metric; fall back to coal-as-legacy
    metrics_sorted = sorted(semantic_metrics)
    suggested_metric = None
    for cand in ("production", "overburden", "dispatch"):
        if cand in semantic_metrics:
            suggested_metric = cand
            break
    if not suggested_metric and metrics_sorted:
        suggested_metric = metrics_sorted[0]

    suggested_commodity = None
    if "coal" in commodities:
        suggested_commodity = "coal"
    elif commodities:
        suggested_commodity = sorted(commodities)[0]

    months_sorted = sorted(months, key=lambda x: x.lower())
    suggested_month = None
    for cand in months_sorted:
        if "march" in cand.lower():
            suggested_month = cand
            break

    # Backward compatible metrics list: semantic first, then raw commodity keys
    # so older clients that still pass metric=coal continue to see it.
    compat_metrics = list(metrics_sorted)
    for raw in sorted(raw_metrics):
        if raw not in compat_metrics:
            # Keep commodity keys available for legacy callers
            from app.analytics.dimensions import COMMODITY_FIELDS, TARGET_FIELDS

            if raw in COMMODITY_FIELDS or raw in TARGET_FIELDS or raw not in semantic_metrics:
                if raw in COMMODITY_FIELDS or raw in TARGET_FIELDS:
                    compat_metrics.append(raw)

    return {
        "domain": resolved,
        "entities": sorted(entities, key=lambda x: x.lower()),
        "commodities": sorted(commodities),
        "commodity_labels": {c: commodity_label(c) for c in sorted(commodities)},
        "metrics": compat_metrics,  # semantic + legacy commodity keys
        "semantic_metrics": metrics_sorted,
        "periods": sorted(periods),
        "reporting_months": months_sorted,
        "measurement_types": sorted(measures),
        "measure_labels": {m: measure_label(m) for m in sorted(measures)},
        "documents": docs,
        "suggested_entity": suggested_entity,
        "suggested_metric": suggested_metric,
        "suggested_commodity": suggested_commodity,
        "suggested_reporting_month": suggested_month,
        "entity_fact_scores": dict(ent_scores),
        "filters_applied": {
            "entity": want_entity,
            "commodity": want_commodity,
            "metric": want_metric,
            "domain": resolved,
        },
    }


def year_wise_trend(
    db: Session,
    *,
    entity: Optional[str],
    metric: str,
    periods: Optional[list[str]] = None,
    document_ids: Optional[list[str]] = None,
    reporting_month: Optional[str] = None,
    measurement_type: Optional[str] = None,
    commodity: Optional[str] = None,
) -> dict[str, Any]:
    metric_n = normalize_field(metric) or metric
    measure = normalize_measure_param(measurement_type)
    storage = storage_metrics_for(commodity=commodity, metric=metric_n, measure=measure)
    if not storage:
        storage = [metric_n]
    warnings: list[str] = []
    for sm in storage:
        if _has_open_conflict(db, entity=entity, metric=sm, periods=periods):
            warnings.append("Open validation conflicts exist — conflicting periods excluded from chart.")
            break

    hits = _merge_hits(
        db,
        entity=entity,
        metric=storage[0],
        metrics=storage,
        periods=periods,
        document_ids=document_ids,
        reporting_month=reporting_month,
        measurement_type=measure,
    )
    if measure is None and any(h.status == "verified_index" for h in hits):
        during = _merge_hits(
            db,
            entity=entity,
            metric=storage[0],
            metrics=storage,
            periods=periods,
            document_ids=document_ids,
            reporting_month=reporting_month,
            measurement_type="during",
        )
        if during:
            hits = during
            measure = "during"

    open_periods: set[str] = set()
    for sm in storage:
        for c in conflicts_for_structured(db, entity=entity, metric=sm, periods=None):
            if c.period:
                open_periods.add(normalize_period(c.period) or c.period)

    by_period: dict[str, StructuredFactHit] = {}
    for h in hits:
        if h.numeric_value is None or not h.period:
            continue
        p = normalize_period(h.period) or h.period
        if p in open_periods:
            continue
        prev = by_period.get(p)
        if prev is None or h.confidence >= prev.confidence:
            by_period[p] = h

    ordered = sorted(by_period.keys())
    points = []
    provenance = []
    source_docs: set[str] = set()
    for p in ordered:
        h = by_period[p]
        prov = _hit_to_prov(h)
        source_docs.add(h.document_name or h.document_id)
        points.append(
            {
                "year": p,
                "period": p,
                "value": h.numeric_value,
                "unit": h.unit,
                "fact_id": h.fact_id,
                "document_id": h.document_id,
                "document_name": h.document_name,
                "page": h.page,
                "sheet_name": h.sheet_name,
                "status": h.status,
            }
        )
        provenance.append(prov.as_dict())

    unit = next((p["unit"] for p in points if p.get("unit")), None)
    cls = classify_raw_metric(metric_n)
    return {
        "chart_type": "line" if len(points) >= 2 else "bar",
        "entity": entity,
        "commodity": normalize_commodity(commodity) or cls.get("commodity"),
        "metric": cls.get("metric") or metric_n,
        "unit": unit,
        "filters": {
            "document_ids": document_ids or [],
            "reporting_month": reporting_month,
            "measurement_type": measure,
            "commodity": normalize_commodity(commodity),
            "periods": periods or [],
            "storage_metrics": storage,
        },
        "source_documents": sorted(source_docs),
        "data": points,
        "provenance": provenance,
        "warnings": warnings,
        "insufficient": len(points) == 0,
        "message": (
            "Insufficient verified structured data for this analysis."
            if len(points) == 0
            else None
        ),
    }


def actual_vs_target(
    db: Session,
    *,
    entity: str,
    period: Optional[str] = None,
    actual_metric: str = "production",
    target_metric: str = "production_target",
    document_ids: Optional[list[str]] = None,
    reporting_month: Optional[str] = None,
    commodity: Optional[str] = None,
) -> dict[str, Any]:
    """Backend-calculated achievement from verified actual + target rows."""
    actual_m = normalize_field(actual_metric) or actual_metric
    target_m = normalize_field(target_metric) or target_metric
    # When commodity is Coal and metric is production, query storage metric=coal for index path
    actual_storage = storage_metrics_for(
        commodity=commodity, metric=actual_m, measure="during"
    ) or [actual_m]
    # Prefer commodity key for index during/target pair
    index_metric = normalize_commodity(commodity) or actual_m
    if index_metric == "production" and normalize_commodity(commodity):
        index_metric = normalize_commodity(commodity) or actual_m
    periods = [period] if period else None
    warnings: list[str] = []

    if _has_open_conflict(db, entity=entity, metric=actual_m, periods=periods) or _has_open_conflict(
        db, entity=entity, metric=target_m, periods=periods
    ):
        warnings.append("Open conflicts for actual/target — values withheld until resolved.")
        return {
            "entity": entity,
            "period": period,
            "actual": None,
            "target": None,
            "achievement_percentage": None,
            "chart_type": "bar",
            "data": [],
            "provenance": [],
            "warnings": warnings,
            "insufficient": True,
            "message": "Insufficient verified structured data for this analysis.",
            "source_documents": [],
            "filters": {
                "document_ids": document_ids or [],
                "reporting_month": reporting_month,
            },
        }

    # Index path: same storage metric with measure during vs target (STRUCTURED_FACT)
    during_index: list = []
    target_index: list = []
    for cand in [index_metric, *actual_storage]:
        if not cand:
            continue
        d = list_index_facts(
            db,
            document_ids=document_ids,
            entity=entity,
            metric=cand,
            fiscal_year=period,
            reporting_month=reporting_month,
            measurement_type="during",
        )
        t = list_index_facts(
            db,
            document_ids=document_ids,
            entity=entity,
            metric=cand,
            fiscal_year=period,
            reporting_month=reporting_month,
            measurement_type="target",
        )
        if d and t:
            during_index, target_index = d, t
            break
        if d and not during_index:
            during_index = d
        if t and not target_index:
            target_index = t

    if during_index and target_index:
        actual_hits = index_facts_as_hits(during_index)
        target_hits = index_facts_as_hits(target_index)
    else:
        # ExtractedFact path: production vs production_target field names
        actual_hits = _merge_hits(
            db,
            entity=entity,
            metric=actual_m,
            metrics=actual_storage,
            periods=periods,
            document_ids=document_ids,
            reporting_month=reporting_month,
            measurement_type="during",
        )
        target_hits = _merge_hits(
            db,
            entity=entity,
            metric=target_m,
            metrics=storage_metrics_for(
                commodity=commodity, metric=actual_m, measure="target"
            )
            or [target_m],
            periods=periods,
            document_ids=document_ids,
            reporting_month=reporting_month,
            measurement_type="target",
        )
    actual_by: dict[str, StructuredFactHit] = {}
    for h in actual_hits:
        if h.numeric_value is None:
            continue
        p = normalize_period(h.period) or h.period or "unknown"
        prev = actual_by.get(p)
        if prev is None or h.confidence >= prev.confidence:
            actual_by[p] = h
    target_by: dict[str, StructuredFactHit] = {}
    for h in target_hits:
        if h.numeric_value is None:
            continue
        p = normalize_period(h.period) or h.period or "unknown"
        prev = target_by.get(p)
        if prev is None or h.confidence >= prev.confidence:
            target_by[p] = h

    keys = sorted(set(actual_by) | set(target_by))
    if period:
        want = normalize_period(period) or period
        keys = [k for k in keys if k == want]

    rows = []
    provenance = []
    source_docs: set[str] = set()
    for p in keys:
        a = actual_by.get(p)
        t = target_by.get(p)
        if not a or not t:
            continue
        # Skip if same fact used for both (no real target)
        if a.fact_id == t.fact_id:
            continue
        actual_v = float(a.numeric_value)
        target_v = float(t.numeric_value)
        achievement = round((actual_v / target_v) * 100.0, 2) if target_v else None
        rows.append(
            {
                "period": p,
                "actual": actual_v,
                "target": target_v,
                "achievement_percentage": achievement,
                "unit": a.unit or t.unit,
                "actual_fact_id": a.fact_id,
                "target_fact_id": t.fact_id,
            }
        )
        provenance.append(_hit_to_prov(a).as_dict())
        provenance.append(_hit_to_prov(t).as_dict())
        source_docs.add(a.document_name or a.document_id)
        source_docs.add(t.document_name or t.document_id)

    if not rows:
        return {
            "entity": entity,
            "period": period,
            "actual": None,
            "target": None,
            "achievement_percentage": None,
            "chart_type": "bar",
            "data": [],
            "provenance": [],
            "warnings": warnings + ["Insufficient verified actual/target pairs."],
            "insufficient": True,
            "message": "Insufficient verified structured data for this analysis.",
            "source_documents": [],
            "filters": {
                "document_ids": document_ids or [],
                "reporting_month": reporting_month,
            },
        }

    primary = rows[-1]
    chart_data = [
        {"label": "Actual", "value": primary["actual"], "unit": primary.get("unit")},
        {"label": "Target", "value": primary["target"], "unit": primary.get("unit")},
    ]
    return {
        "entity": entity,
        "period": primary["period"],
        "actual": primary["actual"],
        "target": primary["target"],
        "achievement_percentage": primary["achievement_percentage"],
        "unit": primary.get("unit"),
        "chart_type": "bar",
        "data": chart_data,
        "series": rows,
        "provenance": provenance,
        "warnings": warnings,
        "insufficient": False,
        "message": None,
        "source_documents": sorted(source_docs),
        "filters": {
            "document_ids": document_ids or [],
            "reporting_month": reporting_month,
            "commodity": normalize_commodity(commodity),
        },
    }


def query_analytics_data(
    db: Session,
    *,
    entity: Optional[str] = None,
    commodity: Optional[str] = None,
    metric: Optional[str] = None,
    measure: Optional[str] = None,
    period: Optional[str] = None,
    periods: Optional[list[str]] = None,
    document_ids: Optional[list[str]] = None,
    reporting_month: Optional[str] = None,
    compare: Optional[str] = None,
    domain: Optional[str] = None,
    seam: Optional[str] = None,
    formation: Optional[str] = None,
) -> dict[str, Any]:
    """Unified structured analytics query: chart series + evidence-backed table.

    Numerical values come only from verified structured facts / index rows,
    or from GeologicalFact rows when domain is geological (never from RAG text).
    """
    resolved = _resolve_analytics_domain(db, domain=domain, document_ids=document_ids)
    if resolved == "geological":
        from app.analytics.geological_adapter import query_geological_analytics_data

        return query_geological_analytics_data(
            db,
            document_ids=document_ids,
            entity=entity,
            metric=metric,
            seam=seam,
            formation=formation,
        )

    metric_n = (normalize_field(metric) or (metric or "").strip().lower()) or "production"
    want_periods = periods or ([period] if period else None)
    measure_n = normalize_measure_param(measure)
    compare_n = normalize_measure_param(compare)

    trend = year_wise_trend(
        db,
        entity=entity,
        metric=metric_n,
        commodity=commodity,
        periods=want_periods,
        document_ids=document_ids,
        reporting_month=reporting_month,
        measurement_type=measure_n,
    )

    avt = None
    if compare_n == "target" or measure_n is None:
        avt = actual_vs_target(
            db,
            entity=entity or "",
            period=period,
            actual_metric=metric_n if metric_n not in {"coal", "lignite", "coking_coal"} else "production",
            document_ids=document_ids,
            reporting_month=reporting_month,
            commodity=commodity,
        )
        if entity and avt.get("insufficient"):
            avt = None

    # Build period table: Actual | Target | Unit | Source | Page
    by_period: dict[str, dict[str, Any]] = {}
    for pt in trend.get("data") or []:
        p = pt.get("period") or pt.get("year")
        if not p:
            continue
        by_period[p] = {
            "period": p,
            "actual": pt.get("value"),
            "target": None,
            "unit": pt.get("unit"),
            "source": pt.get("document_name"),
            "page": pt.get("page"),
            "document_id": pt.get("document_id"),
            "fact_id": pt.get("fact_id"),
            "evidence_available": bool(pt.get("document_id") or pt.get("fact_id")),
        }
    if avt and not avt.get("insufficient"):
        for row in avt.get("series") or []:
            p = row.get("period")
            if not p:
                continue
            entry = by_period.setdefault(
                p,
                {
                    "period": p,
                    "actual": None,
                    "target": None,
                    "unit": row.get("unit"),
                    "source": None,
                    "page": None,
                    "document_id": None,
                    "fact_id": None,
                    "evidence_available": False,
                },
            )
            entry["actual"] = row.get("actual", entry.get("actual"))
            entry["target"] = row.get("target")
            entry["unit"] = row.get("unit") or entry.get("unit")
            entry["achievement_percentage"] = row.get("achievement_percentage")

        # Attach provenance sources for AVT
        for prov in avt.get("provenance") or []:
            p = prov.get("period")
            if not p or p not in by_period:
                continue
            if not by_period[p].get("source"):
                by_period[p]["source"] = prov.get("document_name")
                by_period[p]["page"] = prov.get("page")
                by_period[p]["document_id"] = prov.get("document_id")
                by_period[p]["fact_id"] = prov.get("fact_id")
                by_period[p]["evidence_available"] = bool(prov.get("document_id"))

    table = [by_period[p] for p in sorted(by_period.keys())]
    for row in table:
        if not row.get("evidence_available"):
            row["evidence_note"] = "Evidence unavailable for this value."

    provenance = list(trend.get("provenance") or [])
    if avt and avt.get("provenance"):
        # Prefer trend provenance; AVT adds period coverage already merged into table
        pass

    cls = classify_raw_metric(metric_n)
    return {
        "domain": "production",
        "entity": entity,
        "commodity": normalize_commodity(commodity) or cls.get("commodity"),
        "commodity_label": commodity_label(normalize_commodity(commodity) or cls.get("commodity")),
        "metric": cls.get("metric") or metric_n,
        "measure": measure_n,
        "compare": compare_n,
        "unit": trend.get("unit") or (avt or {}).get("unit"),
        "trend": trend,
        "actual_vs_target": avt,
        "table": table,
        "provenance": provenance,
        "insufficient": bool(trend.get("insufficient") and (not avt or avt.get("insufficient"))),
        "message": trend.get("message") if trend.get("insufficient") else None,
        "llm_context": {
            "domain": "production",
            "entity": entity,
            "commodity": commodity_label(normalize_commodity(commodity) or cls.get("commodity")),
            "metric": cls.get("metric") or metric_n,
            "periods": [
                {
                    "period": r["period"],
                    "actual": r.get("actual"),
                    "target": r.get("target"),
                    "unit": r.get("unit"),
                    "source": r.get("source"),
                    "page": r.get("page"),
                }
                for r in table
            ],
        },
    }


def compare_entities(
    db: Session,
    *,
    entities: list[str],
    metric: str,
    period: Optional[str] = None,
    document_ids: Optional[list[str]] = None,
    reporting_month: Optional[str] = None,
    measurement_type: Optional[str] = None,
) -> dict[str, Any]:
    metric_n = normalize_field(metric) or metric
    periods = [period] if period else None
    warnings: list[str] = []
    bars = []
    provenance = []
    units: set[str] = set()
    source_docs: set[str] = set()

    for ent in entities:
        if _has_open_conflict(db, entity=ent, metric=metric_n, periods=periods):
            warnings.append(f"Skipped {ent}: open validation conflict.")
            continue
        hits = _merge_hits(
            db,
            entity=ent,
            metric=metric_n,
            periods=periods,
            document_ids=document_ids,
            reporting_month=reporting_month,
            measurement_type=measurement_type or "during",
        )
        if not hits and measurement_type is None:
            hits = _merge_hits(
                db,
                entity=ent,
                metric=metric_n,
                periods=periods,
                document_ids=document_ids,
                reporting_month=reporting_month,
            )
        chosen: Optional[StructuredFactHit] = None
        for h in hits:
            if h.numeric_value is None:
                continue
            if period:
                if (normalize_period(h.period) or h.period) == (normalize_period(period) or period):
                    if chosen is None or h.confidence >= chosen.confidence:
                        chosen = h
            else:
                if chosen is None or (h.period or "") > (chosen.period or "") or (
                    h.period == chosen.period and h.confidence >= chosen.confidence
                ):
                    chosen = h
        if not chosen:
            warnings.append(f"No verified {metric_n} for {ent}.")
            continue
        if chosen.unit:
            units.add(chosen.unit.lower())
        bars.append(
            {
                "entity": ent,
                "value": chosen.numeric_value,
                "unit": chosen.unit,
                "period": chosen.period,
                "fact_id": chosen.fact_id,
                "document_id": chosen.document_id,
                "document_name": chosen.document_name,
                "page": chosen.page,
            }
        )
        provenance.append(_hit_to_prov(chosen).as_dict())
        source_docs.add(chosen.document_name or chosen.document_id)

    if len(units) > 1:
        warnings.append("Incompatible units across entities — comparison withheld.")
        return {
            "metric": metric_n,
            "period": period,
            "chart_type": "bar",
            "data": [],
            "provenance": [],
            "warnings": warnings,
            "insufficient": True,
            "message": "Insufficient verified structured data for this analysis.",
            "source_documents": [],
            "filters": {
                "document_ids": document_ids or [],
                "reporting_month": reporting_month,
                "measurement_type": measurement_type,
            },
        }

    return {
        "metric": metric_n,
        "period": period,
        "chart_type": "bar",
        "data": bars,
        "provenance": provenance,
        "warnings": warnings,
        "insufficient": len(bars) == 0,
        "message": (
            "Insufficient verified structured data for this analysis." if len(bars) == 0 else None
        ),
        "source_documents": sorted(source_docs),
        "filters": {
            "document_ids": document_ids or [],
            "reporting_month": reporting_month,
            "measurement_type": measurement_type,
        },
    }


def overview_analytics(db: Session) -> dict[str, Any]:
    """Dashboard-style analytics from live verified data (+ document status counts)."""
    dims = list_dimensions(db)
    facts = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.status.in_(VERIFIED))
        .filter(ExtractedFact.is_calculated.is_(False))
        .all()
    )
    docs = db.query(Document).all()
    by_status: dict[str, int] = defaultdict(int)
    for d in docs:
        by_status[d.status] += 1

    # Top entities by count of verified numeric facts
    ent_counts: dict[str, int] = defaultdict(int)
    ent_prod: dict[str, float] = defaultdict(float)
    for f in facts:
        if not f.entity_name:
            continue
        ent_counts[f.entity_name] += 1
        if (normalize_field(f.field_name) == "production") and f.numeric_value is not None:
            ent_prod[f.entity_name] += float(f.numeric_value)

    top_mines = sorted(
        [
            {
                "mine": e,
                "documents": ent_counts[e],
                "production": round(ent_prod.get(e, 0.0), 2),
            }
            for e in ent_counts
        ],
        key=lambda r: r["production"],
        reverse=True,
    )[:8]

    confs = [f.confidence_score for f in facts if f.confidence_score is not None]
    avg_conf = round(sum(confs) / len(confs), 3) if confs else 0.0

    # Production-like metrics breakdown (label = metric name)
    metric_totals: dict[str, float] = defaultdict(float)
    for f in facts:
        m = normalize_field(f.field_name) or f.field_name
        if m and f.numeric_value is not None and m in {
            "production",
            "overburden",
            "lignite",
            "coal",
            "dispatch",
        }:
            metric_totals[m] += float(f.numeric_value)

    production_by_mineral = [
        {"mineral": k.replace("_", " ").title(), "production": round(v, 2)}
        for k, v in sorted(metric_totals.items(), key=lambda kv: -kv[1])
    ]

    kpis = [
        {"label": "Verified facts", "value": len(facts), "unit": None, "change": None},
        {"label": "Entities", "value": len(dims["entities"]), "unit": None, "change": None},
        {"label": "Metrics tracked", "value": len(dims["metrics"]), "unit": None, "change": None},
        {"label": "Avg confidence", "value": avg_conf, "unit": None, "change": None},
    ]

    # Confidence buckets
    buckets = {"0.9+": 0, "0.8–0.9": 0, "0.7–0.8": 0, "<0.7": 0}
    for c in confs:
        if c >= 0.9:
            buckets["0.9+"] += 1
        elif c >= 0.8:
            buckets["0.8–0.9"] += 1
        elif c >= 0.7:
            buckets["0.7–0.8"] += 1
        else:
            buckets["<0.7"] += 1

    monthly: dict[str, int] = defaultdict(int)
    for d in docs:
        if d.created_at:
            key = d.created_at.strftime("%Y-%m")
            monthly[key] += 1

    return {
        "kpis": kpis,
        "production_by_mineral": production_by_mineral,
        "documents_by_status": [{"status": k, "count": v} for k, v in sorted(by_status.items())],
        "monthly_uploads": [{"month": k, "uploads": monthly[k]} for k in sorted(monthly)],
        "confidence_distribution": [{"bucket": k, "count": v} for k, v in buckets.items()],
        "top_mines": top_mines,
        "dimensions": dims,
    }
