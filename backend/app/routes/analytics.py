"""Analytics API — verified structured data with provenance (USER + ADMIN)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.analytics import service as analytics_service
from app.auth.deps import AuthUser, require_permission
from app.database import get_db
from app.schemas import AnalyticsResponse

router = APIRouter()


def _doc_ids(document_id: Optional[list[str]]) -> Optional[list[str]]:
    if not document_id:
        return None
    return [d for d in document_id if d]


@router.get("", response_model=AnalyticsResponse)
def get_analytics(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> AnalyticsResponse:
    """Overview analytics from verified facts (replaces static demo when data exists)."""
    data = analytics_service.overview_analytics(db)
    return AnalyticsResponse(**{k: data[k] for k in AnalyticsResponse.model_fields})


@router.get("/dimensions")
def analytics_dimensions(
    document_id: Optional[list[str]] = Query(None),
    entity: Optional[str] = None,
    commodity: Optional[str] = None,
    metric: Optional[str] = None,
    domain: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict:
    """Dimension lists with optional dependent filters (entity → commodity → metric → period)."""
    return analytics_service.list_dimensions(
        db,
        document_ids=_doc_ids(document_id),
        entity=entity,
        commodity=commodity,
        metric=metric,
        domain=domain,
    )


@router.get("/data")
def analytics_data(
    entity: Optional[str] = None,
    commodity: Optional[str] = None,
    metric: Optional[str] = None,
    measure: Optional[str] = None,
    period: Optional[str] = None,
    periods: Optional[list[str]] = Query(None),
    document_id: Optional[list[str]] = Query(None),
    reporting_month: Optional[str] = None,
    compare: Optional[str] = None,
    domain: Optional[str] = None,
    seam: Optional[str] = None,
    formation: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict:
    """Unified structured Analytics query — chart + evidence table (no vector search)."""
    resolved = analytics_service._resolve_analytics_domain(
        db, domain=domain, document_ids=_doc_ids(document_id)
    )
    if resolved != "geological" and not metric and not commodity:
        raise HTTPException(status_code=400, detail="metric or commodity is required")
    return analytics_service.query_analytics_data(
        db,
        entity=entity,
        commodity=commodity,
        metric=metric or ("production" if resolved != "geological" else None),
        measure=measure,
        period=period,
        periods=periods,
        document_ids=_doc_ids(document_id),
        reporting_month=reporting_month,
        compare=compare,
        domain=domain or resolved,
        seam=seam,
        formation=formation,
    )


@router.get("/trend")
def analytics_trend(
    metric: str = Query(..., min_length=1),
    entity: Optional[str] = None,
    commodity: Optional[str] = None,
    period: Optional[list[str]] = Query(None),
    document_id: Optional[list[str]] = Query(None),
    reporting_month: Optional[str] = None,
    measurement_type: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict:
    return analytics_service.year_wise_trend(
        db,
        entity=entity,
        metric=metric,
        commodity=commodity,
        periods=period,
        document_ids=_doc_ids(document_id),
        reporting_month=reporting_month,
        measurement_type=measurement_type,
    )


@router.get("/actual-vs-target")
def analytics_actual_vs_target(
    entity: str = Query(..., min_length=1),
    period: Optional[str] = None,
    actual_metric: str = "production",
    target_metric: str = "production_target",
    commodity: Optional[str] = None,
    document_id: Optional[list[str]] = Query(None),
    reporting_month: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict:
    return analytics_service.actual_vs_target(
        db,
        entity=entity,
        period=period,
        actual_metric=actual_metric,
        target_metric=target_metric,
        commodity=commodity,
        document_ids=_doc_ids(document_id),
        reporting_month=reporting_month,
    )


@router.get("/compare")
def analytics_compare(
    entities: list[str] = Query(..., min_length=1),
    metric: str = Query(..., min_length=1),
    period: Optional[str] = None,
    document_id: Optional[list[str]] = Query(None),
    reporting_month: Optional[str] = None,
    measurement_type: Optional[str] = None,
    commodity: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict:
    if len(entities) < 1:
        raise HTTPException(status_code=400, detail="At least one entity is required.")
    # Resolve commodity-aware storage metric for compare
    from app.analytics.dimensions import storage_metrics_for

    storage = storage_metrics_for(commodity=commodity, metric=metric) or [metric]
    return analytics_service.compare_entities(
        db,
        entities=entities,
        metric=storage[0],
        period=period,
        document_ids=_doc_ids(document_id),
        reporting_month=reporting_month,
        measurement_type=measurement_type,
    )
