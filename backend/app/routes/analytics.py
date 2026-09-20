"""Analytics API — verified structured data with provenance."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.analytics import service as analytics_service
from app.database import get_db
from app.schemas import AnalyticsResponse

router = APIRouter()


def _doc_ids(document_id: Optional[list[str]]) -> Optional[list[str]]:
    if not document_id:
        return None
    return [d for d in document_id if d]


@router.get("", response_model=AnalyticsResponse)
def get_analytics(db: Session = Depends(get_db)) -> AnalyticsResponse:
    """Overview analytics from verified facts (replaces static demo when data exists)."""
    data = analytics_service.overview_analytics(db)
    return AnalyticsResponse(**{k: data[k] for k in AnalyticsResponse.model_fields})


@router.get("/dimensions")
def analytics_dimensions(
    document_id: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    return analytics_service.list_dimensions(db, document_ids=_doc_ids(document_id))


@router.get("/trend")
def analytics_trend(
    metric: str = Query(..., min_length=1),
    entity: Optional[str] = None,
    period: Optional[list[str]] = Query(None),
    document_id: Optional[list[str]] = Query(None),
    reporting_month: Optional[str] = None,
    measurement_type: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    return analytics_service.year_wise_trend(
        db,
        entity=entity,
        metric=metric,
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
    document_id: Optional[list[str]] = Query(None),
    reporting_month: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    return analytics_service.actual_vs_target(
        db,
        entity=entity,
        period=period,
        actual_metric=actual_metric,
        target_metric=target_metric,
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
    db: Session = Depends(get_db),
) -> dict:
    if len(entities) < 1:
        raise HTTPException(status_code=400, detail="At least one entity is required.")
    return analytics_service.compare_entities(
        db,
        entities=entities,
        metric=metric,
        period=period,
        document_ids=_doc_ids(document_id),
        reporting_month=reporting_month,
        measurement_type=measurement_type,
    )
