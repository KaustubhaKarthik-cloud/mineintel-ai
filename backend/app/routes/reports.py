"""Reports — generate, list, view, and download real report records."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import AuthUser, require_permission
from app.database import get_db
from app.models import Report
from app.reports.html import ensure_styled_html
from app.reports.service import build_full_report, export_report_excel, export_report_pdf
from app.services.audit import write_audit

router = APIRouter()


class GenerateReportRequest(BaseModel):
    title: Optional[str] = None
    report_type: str = "summary"
    domain: str = Field(
        default="mining",
        description="mining | geological | combined",
    )
    entity: Optional[str] = None
    metric: Optional[str] = "production"
    period: Optional[str] = None
    document_ids: Optional[list[str]] = None
    compare_entities: Optional[list[str]] = None
    sections: Optional[list[str]] = None
    generated_by: Optional[str] = None


def _report_out(r: Report) -> dict[str, Any]:
    params = r.parameters if isinstance(r.parameters, dict) else {}
    return {
        "id": r.id,
        "title": r.title,
        "report_type": r.report_type,
        "status": r.status,
        "generated_by": r.generated_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "domain": params.get("domain") or r.report_type,
        "source_documents": params.get("source_documents") or [],
        "source_document_ids": r.source_document_ids or params.get("document_ids") or [],
        "selected_entities": r.selected_entities or [],
        "selected_periods": r.selected_periods or [],
        "output_format": r.output_format or "html",
        "output_path": r.output_path,
        "parameters": {
            k: v for k, v in params.items() if k != "export_bundle"
        },
        "has_content": bool(r.content),
        "provenance_count": len(r.provenance or []) if isinstance(r.provenance, list) else 0,
        "warnings": params.get("warnings") or [],
        "pending_verification": bool(params.get("pending_verification")),
        "review_required_count": params.get("review_required_count") or 0,
        "open_conflicts": params.get("open_conflicts") or 0,
        "insufficient": bool(params.get("insufficient")),
    }


@router.get("")
def list_reports(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("reports.read")),
) -> dict[str, Any]:
    rows = db.query(Report).order_by(Report.created_at.desc()).all()
    return {"total": len(rows), "items": [_report_out(r) for r in rows]}


@router.post("/generate")
def generate_report(
    body: GenerateReportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("reports.generate")),
) -> dict[str, Any]:
    actor = body.generated_by or user.username
    try:
        report = build_full_report(
            db,
            title=body.title,
            report_type=body.report_type,
            domain=body.domain,
            entity=body.entity,
            metric=body.metric,
            period=body.period,
            document_ids=body.document_ids,
            compare_entities_list=body.compare_entities,
            sections=body.sections,
            generated_by=actor,
            created_by_user_id=user.id,
        )
    except Exception as exc:  # noqa: BLE001
        write_audit(
            db,
            action="REPORT_GENERATE_FAILED",
            actor=actor,
            entity_type="report",
            details={"error": str(exc)[:300], "domain": body.domain},
            ip_address=request.client.host if request.client else None,
            commit=True,
        )
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}") from exc

    write_audit(
        db,
        action="REPORT_GENERATED",
        actor=actor,
        entity_type="report",
        entity_id=report.id,
        details={
            "title": report.title,
            "domain": (report.parameters or {}).get("domain"),
            "source_documents": (report.parameters or {}).get("source_documents"),
            "fact_count": (report.parameters or {}).get("fact_count"),
            "geo_fact_count": (report.parameters or {}).get("geo_fact_count"),
        },
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    return _report_out(report)


@router.get("/{report_id}")
def get_report(
    report_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("reports.read")),
) -> dict[str, Any]:
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    out = _report_out(r)
    out["content"] = r.content
    out["provenance"] = r.provenance or []
    return out


@router.get("/{report_id}/view")
def view_report(
    report_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("reports.read")),
):
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    write_audit(
        db,
        action="REPORT_VIEWED",
        actor=user.username,
        entity_type="report",
        entity_id=report_id,
        details={"title": r.title},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    if r.output_path and Path(r.output_path).is_file() and (r.output_format or "html") == "html":
        return FileResponse(r.output_path, media_type="text/html")
    content = ensure_styled_html(r.title or "Report", r.content or "")
    return HTMLResponse(content)


@router.get("/{report_id}/download")
def download_report(
    report_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("reports.read")),
):
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    write_audit(
        db,
        action="REPORT_DOWNLOADED",
        actor=user.username,
        entity_type="report",
        entity_id=report_id,
        details={"title": r.title, "format": "html"},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    filename = f"{(r.title or 'report').replace(' ', '_')[:80]}.html"
    if r.output_path and Path(r.output_path).is_file():
        return FileResponse(
            r.output_path,
            media_type="text/html",
            filename=filename,
            content_disposition_type="attachment",
        )
    content = ensure_styled_html(r.title or "Report", r.content or "")
    return HTMLResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{report_id}/pdf")
def download_report_pdf(
    report_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("reports.read")),
):
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        pdf_path = export_report_pdf(db, r)
    except Exception as exc:  # noqa: BLE001
        write_audit(
            db,
            action="REPORT_PDF_EXPORT_FAILED",
            actor=user.username,
            entity_type="report",
            entity_id=report_id,
            details={"error": str(exc)[:300]},
            ip_address=request.client.host if request.client else None,
            commit=True,
        )
        raise HTTPException(status_code=500, detail=f"PDF export failed: {exc}") from exc

    write_audit(
        db,
        action="REPORT_PDF_EXPORTED",
        actor=user.username,
        entity_type="report",
        entity_id=report_id,
        details={"title": r.title, "path": str(pdf_path)},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    filename = f"{(r.title or 'report').replace(' ', '_')[:80]}.pdf"
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=filename,
        content_disposition_type="attachment",
    )


@router.get("/{report_id}/excel")
def download_report_excel(
    report_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("reports.read")),
):
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        xlsx_path = export_report_excel(db, r)
    except Exception as exc:  # noqa: BLE001
        write_audit(
            db,
            action="REPORT_EXCEL_EXPORT_FAILED",
            actor=user.username,
            entity_type="report",
            entity_id=report_id,
            details={"error": str(exc)[:300]},
            ip_address=request.client.host if request.client else None,
            commit=True,
        )
        raise HTTPException(status_code=500, detail=f"Excel export failed: {exc}") from exc

    write_audit(
        db,
        action="REPORT_EXCEL_EXPORTED",
        actor=user.username,
        entity_type="report",
        entity_id=report_id,
        details={"title": r.title, "path": str(xlsx_path)},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    filename = f"{(r.title or 'report').replace(' ', '_')[:80]}.xlsx"
    return FileResponse(
        str(xlsx_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        content_disposition_type="attachment",
    )


@router.delete("/{report_id}")
def delete_report(
    report_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("reports.delete")),
) -> dict[str, str]:
    r = db.query(Report).filter(Report.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    title = r.title
    for suffix in (".html", ".pdf", ".xlsx"):
        p = Path(r.output_path) if r.output_path else None
        candidates = []
        if p:
            candidates.append(p)
            candidates.append(p.with_suffix(suffix))
        from app.utils.files import documents_root

        candidates.append(documents_root() / "reports" / f"{report_id}{suffix}")
        for path in candidates:
            try:
                if path and path.is_file():
                    path.unlink(missing_ok=True)
            except OSError:
                pass
    db.delete(r)
    write_audit(
        db,
        action="REPORT_DELETED",
        actor=user.username,
        entity_type="report",
        entity_id=report_id,
        details={"title": title},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    return {"status": "deleted", "id": report_id}
