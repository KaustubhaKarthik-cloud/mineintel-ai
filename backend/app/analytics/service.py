"""Phase 6 analytics — verified structured facts only (no LLM-invented numbers)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.analytics.index_facts import (
    _is_plausible_entity,
    index_fact_dimensions,
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
) -> list[StructuredFactHit]:
    """Prefer indexed STRUCTURED_FACT chunks; also include verified ExtractedFact rows."""
    index_rows = list_index_facts(
        db,
        document_ids=document_ids,
        entity=entity,
        metric=metric,
        fiscal_year=periods[0] if periods and len(periods) == 1 else None,
        reporting_month=reporting_month,
        measurement_type=measurement_type,
    )
    if periods and len(periods) > 1:
        want = {normalize_period(p) for p in periods if normalize_period(p)}
        index_rows = [r for r in index_rows if r.fiscal_year in want]

    hits = index_facts_as_hits(index_rows)
    extracted = retrieve_structured_facts(
        db,
        entity=entity,
        metric=metric,
        periods=periods,
        verified_only=True,
    )
    if document_ids:
        allowed = set(document_ids)
        extracted = [h for h in extracted if h.document_id in allowed]

    seen: set[tuple] = set()
    merged: list[StructuredFactHit] = []
    for h in hits + extracted:
        key = (
            (h.entity or "").lower(),
            h.metric,
            h.period,
            round(float(h.numeric_value), 6) if h.numeric_value is not None else None,
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(h)
    return merged


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


def list_dimensions(
    db: Session,
    *,
    document_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Entities / metrics / periods from index facts + verified ExtractedFact rows."""
    idx = index_fact_dimensions(db, document_ids=document_ids)
    entities: set[str] = set(idx["entities"])
    metrics: set[str] = set(idx["metrics"])
    periods: set[str] = set(idx["periods"])
    months: set[str] = set(idx.get("reporting_months") or [])
    measures: set[str] = set(idx.get("measurement_types") or [])

    q = (
        db.query(ExtractedFact)
        .filter(ExtractedFact.status.in_(VERIFIED))
        .filter(ExtractedFact.is_calculated.is_(False))
        .filter(ExtractedFact.numeric_value.isnot(None))
    )
    if document_ids:
        q = q.filter(ExtractedFact.document_id.in_(document_ids))
    for f in q.all():
        if f.entity_name and _is_plausible_entity(f.entity_name):
            entities.add(f.entity_name)
        m = normalize_field(f.field_name) or f.field_name
        if m:
            metrics.add(m)
        p = normalize_period(f.financial_year)
        if p:
            periods.add(p)

    docs = list_analytics_documents(db)
    if document_ids:
        allowed = set(document_ids)
        docs = [d for d in docs if d["id"] in allowed]

    return {
        "entities": sorted(entities, key=lambda x: x.lower()),
        "metrics": sorted(metrics),
        "periods": sorted(periods),
        "reporting_months": sorted(months, key=lambda x: x.lower()),
        "measurement_types": sorted(measures),
        "documents": docs,
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
) -> dict[str, Any]:
    metric_n = normalize_field(metric) or metric
    warnings: list[str] = []
    if _has_open_conflict(db, entity=entity, metric=metric_n, periods=periods):
        warnings.append("Open validation conflicts exist — conflicting periods excluded from chart.")

    # Default measure for production-like trends: prefer "during" when available
    measure = measurement_type
    hits = _merge_hits(
        db,
        entity=entity,
        metric=metric_n,
        periods=periods,
        document_ids=document_ids,
        reporting_month=reporting_month,
        measurement_type=measure,
    )
    if measure is None and any(h.status == "verified_index" for h in hits):
        # Prefer during measurements for cleaner year series when mixed measures exist
        during = _merge_hits(
            db,
            entity=entity,
            metric=metric_n,
            periods=periods,
            document_ids=document_ids,
            reporting_month=reporting_month,
            measurement_type="during",
        )
        if during:
            hits = during

    open_periods: set[str] = set()
    for c in conflicts_for_structured(db, entity=entity, metric=metric_n, periods=None):
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
    return {
        "chart_type": "line" if len(points) >= 2 else "bar",
        "entity": entity,
        "metric": metric_n,
        "unit": unit,
        "filters": {
            "document_ids": document_ids or [],
            "reporting_month": reporting_month,
            "measurement_type": measure,
            "periods": periods or [],
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
) -> dict[str, Any]:
    """Backend-calculated achievement from verified actual + target rows."""
    actual_m = normalize_field(actual_metric) or actual_metric
    target_m = normalize_field(target_metric) or target_metric
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

    # Index path: same metric with measure during vs target (STRUCTURED_FACT chunks)
    during_index = list_index_facts(
        db,
        document_ids=document_ids,
        entity=entity,
        metric=actual_m,
        fiscal_year=period,
        reporting_month=reporting_month,
        measurement_type="during",
    )
    target_index = list_index_facts(
        db,
        document_ids=document_ids,
        entity=entity,
        metric=actual_m,
        fiscal_year=period,
        reporting_month=reporting_month,
        measurement_type="target",
    )

    if during_index and target_index:
        actual_hits = index_facts_as_hits(during_index)
        target_hits = index_facts_as_hits(target_index)
    else:
        # ExtractedFact path: production vs production_target field names
        actual_hits = _merge_hits(
            db,
            entity=entity,
            metric=actual_m,
            periods=periods,
            document_ids=document_ids,
            reporting_month=reporting_month,
        )
        target_hits = _merge_hits(
            db,
            entity=entity,
            metric=target_m,
            periods=periods,
            document_ids=document_ids,
            reporting_month=reporting_month,
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
