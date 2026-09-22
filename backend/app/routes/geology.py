"""Geological Explorer + Analytics API (G4).

Reuses GeologicalFact structured data. Numerical analytics are never LLM-generated.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import AuthUser, require_permission
from app.database import get_db
from app.geology import explorer as geo_explorer
from app.geology import geo_analytics
from app.services.audit import write_audit

router = APIRouter()


class ExplainRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    analytic: str = Field(
        "resources_by_seam",
        description="resources_by_seam | formation_seam | borehole_depths | seam_thickness | summary | compare",
    )
    document_id: Optional[str] = None
    document_id_b: Optional[str] = None
    formation: Optional[str] = None
    seam: Optional[str] = None
    evidence: Optional[dict[str, Any]] = None


@router.get("/explorer")
def get_explorer(
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    seam: Optional[str] = None,
    borehole: Optional[str] = None,
    metric: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    data = geo_explorer.explorer_overview(
        db,
        document_id=document_id,
        formation=formation,
        seam=seam,
        borehole=borehole,
        metric=metric,
        status=status,
    )
    write_audit(
        db,
        action="geology.explorer.view",
        actor=user.username,
        entity_type="geological_explorer",
        entity_id=document_id,
        details={"filters": {"formation": formation, "seam": seam, "metric": metric}},
    )
    return data


@router.get("/dimensions")
def get_dimensions(
    document_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    return geo_explorer.filter_dimensions(db, document_id=document_id)


@router.get("/documents")
def get_documents(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    items = geo_explorer.list_geological_documents(db)
    return {"total": len(items), "items": items}


@router.get("/documents/{document_id}/summary")
def get_document_summary(
    document_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    from app.models import Document

    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return geo_explorer.document_summary(db, document_id)


@router.get("/facts")
def get_facts(
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    seam: Optional[str] = None,
    borehole: Optional[str] = None,
    metric: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    rows = geo_explorer.query_geological_facts(
        db,
        document_id=document_id,
        formation=formation,
        seam=seam,
        borehole=borehole,
        metric=metric,
        status=status,
        limit=limit,
        offset=offset,
    )
    docs = geo_explorer._doc_map(db, {r.document_id for r in rows})
    items = [
        geo_explorer.fact_to_explorer_item(r, docs.get(r.document_id)) for r in rows
    ]
    return {"total": len(items), "items": items, "offset": offset, "limit": limit}


@router.get("/facts/{fact_id}")
def get_fact_detail(
    fact_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    item = geo_explorer.get_fact_detail(db, fact_id)
    if not item:
        raise HTTPException(status_code=404, detail="Geological fact not found")
    return item


@router.get("/formations")
def get_formations(
    document_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    items = geo_explorer.list_formations(db, document_id=document_id, status=status)
    return {"total": len(items), "items": items}


@router.get("/seams")
def get_seams(
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    items = geo_explorer.list_seams(
        db, document_id=document_id, formation=formation, status=status
    )
    return {"total": len(items), "items": items}


@router.get("/boreholes")
def get_boreholes(
    document_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    items = geo_explorer.list_boreholes(db, document_id=document_id, status=status)
    return {"total": len(items), "items": items}


@router.get("/analytics")
def get_analytics_bundle(
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    seam: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict[str, Any]:
    return geo_analytics.analytics_bundle(
        db, document_id=document_id, formation=formation, seam=seam
    )


@router.get("/analytics/resources")
def analytics_resources(
    document_id: Optional[str] = None,
    formation: Optional[str] = None,
    seam: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict[str, Any]:
    return geo_analytics.resources_by_seam(
        db,
        document_id=document_id,
        formation=formation,
        seam=seam,
        status=status,
    )


@router.get("/analytics/formations")
def analytics_formations(
    document_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict[str, Any]:
    return geo_analytics.formation_seam_distribution(
        db, document_id=document_id, status=status
    )


@router.get("/analytics/boreholes")
def analytics_boreholes(
    document_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict[str, Any]:
    return geo_analytics.borehole_depth_summary(
        db, document_id=document_id, status=status
    )


@router.get("/analytics/thickness")
def analytics_thickness(
    document_id: Optional[str] = None,
    seam: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict[str, Any]:
    return geo_analytics.seam_thickness_analytic(
        db, document_id=document_id, seam=seam, status=status
    )


@router.get("/analytics/summary")
def analytics_summary(
    document_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict[str, Any]:
    return geo_analytics.geological_fact_summary(db, document_id=document_id)


@router.get("/compare")
def compare_documents(
    document_id_a: str = Query(..., min_length=1),
    document_id_b: str = Query(..., min_length=1),
    metric: Optional[list[str]] = Query(None),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics")),
) -> dict[str, Any]:
    result = geo_analytics.compare_documents(
        db, document_id_a, document_id_b, metrics=metric
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    write_audit(
        db,
        action="geology.compare",
        actor=user.username,
        entity_type="geological_compare",
        details={"document_id_a": document_id_a, "document_id_b": document_id_b},
    )
    return result


@router.get("/locations")
def geological_locations(
    document_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("explore")),
) -> dict[str, Any]:
    """Document-grounded map locations — explicit coordinates only, never invented."""
    from app.geology.coordinates import list_document_locations

    return list_document_locations(db, document_id=document_id)


@router.post("/analytics/explain")
def explain_analytics(
    body: ExplainRequest,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("assistant")),
) -> dict[str, Any]:
    """Explain analytics from structured evidence. LLM must not invent numbers."""
    evidence = body.evidence
    if evidence is None:
        analytic = (body.analytic or "resources_by_seam").lower()
        if analytic in {"resources_by_seam", "resources", "resource"}:
            evidence = geo_analytics.resources_by_seam(
                db,
                document_id=body.document_id,
                formation=body.formation,
                seam=body.seam,
            )
        elif analytic in {"formation_seam", "formations"}:
            evidence = geo_analytics.formation_seam_distribution(
                db, document_id=body.document_id
            )
        elif analytic in {"borehole_depths", "boreholes"}:
            evidence = geo_analytics.borehole_depth_summary(
                db, document_id=body.document_id
            )
        elif analytic in {"seam_thickness", "thickness"}:
            evidence = geo_analytics.seam_thickness_analytic(
                db, document_id=body.document_id, seam=body.seam
            )
        elif analytic == "summary":
            evidence = {
                "summary": geo_analytics.geological_fact_summary(
                    db, document_id=body.document_id
                ),
                "items": [],
                "empty": False,
            }
        elif analytic == "compare":
            if not body.document_id or not body.document_id_b:
                raise HTTPException(
                    status_code=400,
                    detail="document_id and document_id_b are required for compare explanation.",
                )
            evidence = geo_analytics.compare_documents(
                db, body.document_id, body.document_id_b
            )
            evidence["items"] = evidence.get("comparisons") or []
        else:
            raise HTTPException(status_code=400, detail=f"Unknown analytic: {body.analytic}")

    result = geo_analytics.explain_analytics(question=body.question, evidence=evidence)
    write_audit(
        db,
        action="geology.analytics.explain",
        actor=user.username,
        entity_type="geological_analytics",
        details={"analytic": body.analytic, "question": body.question[:200]},
    )
    return result
