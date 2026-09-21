"""Phase 7 report builder — verified structured data + provenance (no invented numbers)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.analytics.index_facts import list_index_facts
from app.analytics.service import actual_vs_target, compare_entities, list_dimensions, year_wise_trend
from app.models import Document, Report
from app.reports.export_excel import write_report_excel
from app.reports.export_pdf import write_report_pdf
from app.reports.geo_sections import (
    DISCLAIMER,
    build_geological_html_sections,
    collect_geological_payload,
)
from app.reports.html import build_summary_html, esc, prefer_entity, wrap_report_document
from app.utils.files import documents_root
from app.validation.service import list_conflicts


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def build_full_report(
    db: Session,
    *,
    title: Optional[str] = None,
    report_type: str = "summary",
    domain: str = "mining",
    entity: Optional[str] = None,
    metric: Optional[str] = None,
    period: Optional[str] = None,
    document_ids: Optional[list[str]] = None,
    compare_entities_list: Optional[list[str]] = None,
    sections: Optional[list[str]] = None,
    generated_by: str = "ops.analyst",
    created_by_user_id: Optional[str] = None,
) -> Report:
    """Build mining, geological, or combined report from live application data."""
    domain_l = (domain or "mining").strip().lower()
    if domain_l in {"geo", "geology", "geological"}:
        domain_l = "geological"
    elif domain_l in {"both", "all", "combined"}:
        domain_l = "combined"
    else:
        domain_l = "mining"

    wanted = set(s.lower() for s in (sections or []))
    include_mining = domain_l in {"mining", "combined"}
    include_geo = domain_l in {"geological", "combined"}
    if wanted:
        include_mining = include_mining and (
            not wanted
            or bool(wanted & {"mining", "facts", "analytics", "validation", "summary"})
            or domain_l == "mining"
        )
        include_geo = include_geo and (
            bool(wanted & {"geological", "geology", "formations", "seams", "resources", "boreholes"})
            or domain_l in {"geological", "combined"}
        )
        if domain_l == "combined" and not wanted:
            include_mining = include_geo = True

    generated_at = _now_utc()
    geo_payload: dict[str, Any] = {}
    if include_geo:
        geo_payload = collect_geological_payload(db, document_ids=document_ids)

    # ── Mining branch ────────────────────────────────────────
    dims = {"entities": [], "metrics": [], "periods": []}
    trend: dict[str, Any] = {"insufficient": True, "data": [], "provenance": []}
    avt = None
    compare = None
    facts = []
    conflicts = []
    peers: list[str] = []
    source_docs: list[str] = []

    if include_mining:
        dims = list_dimensions(db, document_ids=document_ids)
        entity = prefer_entity(dims["entities"], entity)
        metric = metric or (
            "coal"
            if "coal" in dims["metrics"]
            else (dims["metrics"][0] if dims["metrics"] else "production")
        )

        trend = year_wise_trend(
            db,
            entity=entity,
            metric=metric,
            periods=[period] if period else None,
            document_ids=document_ids,
        )
        avt = (
            actual_vs_target(db, entity=entity, period=period, document_ids=document_ids)
            if entity
            else None
        )

        peers = list(compare_entities_list or [])
        if entity and entity not in peers:
            peers = [entity] + peers
        if len(peers) < 2:
            for e in dims["entities"]:
                if e not in peers:
                    peers.append(e)
                if len(peers) >= 4:
                    break
        compare = (
            compare_entities(
                db,
                entities=peers[:6],
                metric=metric,
                period=period,
                document_ids=document_ids,
            )
            if len(peers) >= 2
            else None
        )

        facts = list_index_facts(
            db,
            document_ids=document_ids,
            entity=entity,
            metric=metric,
            fiscal_year=period,
            limit=500,
        )

        conflicts = [c for c in list_conflicts(db) if c.status not in {"dismissed", "resolved"}]
        if document_ids:
            allowed = set(document_ids)
            filtered = []
            for c in conflicts:
                evid_docs = {e.document_id for e in (c.evidence_items or []) if e.document_id}
                if not evid_docs or evid_docs & allowed:
                    filtered.append(c)
            conflicts = filtered

        source_docs = sorted(
            {
                *(trend.get("source_documents") or []),
                *((avt or {}).get("source_documents") or []),
                *((compare or {}).get("source_documents") or []),
                *[f.document_name for f in facts],
            }
        )

    if document_ids:
        for d in db.query(Document).filter(Document.id.in_(document_ids)).all():
            name = d.original_filename or d.filename
            if name not in source_docs:
                source_docs.append(name)
    for d in geo_payload.get("documents") or []:
        name = d.get("document_name")
        if name and name not in source_docs:
            source_docs.append(name)

    # Title
    if title:
        report_title = title
    elif domain_l == "geological":
        report_title = "Geological intelligence report"
    elif domain_l == "combined":
        report_title = "Combined mining & geological intelligence report"
    else:
        report_title = f"{entity or 'Mining'} {metric or 'metrics'} intelligence report"
    if period:
        report_title = f"{report_title} ({period})"

    # Build HTML
    if include_mining and domain_l != "geological":
        base_html = build_summary_html(
            title=report_title,
            entity=entity,
            metric=metric or "production",
            period=period,
            trend=trend,
            avt=avt,
            facts=facts,
            source_docs=source_docs,
        )
    else:
        chips = [
            f'<span class="chip">Domain · {esc(domain_l)}</span>',
            f'<span class="chip">Generated · {esc(generated_at)}</span>',
        ]
        body = [
            '<section class="hero">',
            f"<h2>{esc(report_title)}</h2>",
            f'<div class="meta"><span><strong>Generated</strong> {esc(generated_at)}</span></div>',
            f'<div class="chips">{"".join(chips)}</div>',
            "</section>",
            '<section class="section"><h3>Source documents</h3><ul class="docs">',
        ]
        if source_docs:
            for d in source_docs:
                body.append(f"<li>{esc(d)}</li>")
        else:
            body.append("<li>No source documents linked</li>")
        body.append("</ul></section>")
        base_html = wrap_report_document(report_title, "\n".join(body), generated_at=generated_at)

    extra_sections: list[str] = []

    if include_mining:
        extra_sections.append('<section class="section"><h3>Executive summary</h3>')
        bullets: list[str] = []
        if entity and not trend.get("insufficient") and trend.get("data"):
            latest = trend["data"][-1]
            page_bit = (
                f", page {latest.get('page')}" if latest.get("page") is not None else ""
            )
            bullets.append(
                f"<li><strong>{esc(entity)}</strong> {esc(metric)} latest period "
                f"<strong>{esc(latest.get('period'))}</strong>: "
                f"<span class='num'>{esc(latest.get('value'))}</span> {esc(latest.get('unit') or '')} "
                f"(source: {esc(latest.get('document_name') or '')}{esc(page_bit)}).</li>"
            )
        if avt and not avt.get("insufficient"):
            bullets.append(
                f"<li>Actual vs target for <strong>{esc(entity)}</strong>: "
                f"{esc(avt.get('actual'))} / {esc(avt.get('target'))} {esc(avt.get('unit') or '')} "
                f"(achievement {esc(avt.get('achievement_percentage'))}%).</li>"
            )
        if compare and not compare.get("insufficient"):
            parts = [
                f"{esc(r.get('entity'))}={esc(r.get('value'))} {esc(r.get('unit') or '')}"
                for r in (compare.get("data") or [])
            ]
            bullets.append(f"<li>Entity comparison ({esc(metric)}): {', '.join(parts)}.</li>")
        if conflicts:
            bullets.append(
                f"<li><strong>{len(conflicts)}</strong> open validation conflict(s) require human review.</li>"
            )
        if not bullets and domain_l == "mining":
            bullets.append(
                "<li>Insufficient verified structured data for a numerical executive summary. "
                "Index documents and verify facts, then regenerate.</li>"
            )
        if bullets:
            extra_sections.append("<ul>" + "".join(bullets) + "</ul></section>")
        else:
            extra_sections.append("</section>")

        if conflicts:
            extra_sections.append(
                '<section class="section"><h3>Detected discrepancies / validation</h3>'
            )
            extra_sections.append('<div class="table-wrap"><table><thead><tr>')
            for col in ("Entity", "Field", "Period", "Severity", "Status", "Description"):
                extra_sections.append(f"<th>{col}</th>")
            extra_sections.append("</tr></thead><tbody>")
            for c in conflicts[:40]:
                extra_sections.append(
                    "<tr>"
                    f"<td>{esc(c.entity_name)}</td>"
                    f"<td>{esc(c.field_name)}</td>"
                    f"<td>{esc(c.period)}</td>"
                    f"<td>{esc(c.severity)}</td>"
                    f"<td>{esc(c.status)}</td>"
                    f"<td>{esc((c.description or '')[:180])}</td>"
                    "</tr>"
                )
            extra_sections.append("</tbody></table></div></section>")

    if include_geo:
        extra_sections.append(build_geological_html_sections(geo_payload))

    extra_sections.append(
        f'<section class="section"><h3>Disclaimer</h3><p>{esc(DISCLAIMER)}</p></section>'
    )

    inject = "\n".join(extra_sections)
    if '<p class="footer">' in base_html:
        content = base_html.replace('<p class="footer">', inject + '\n<p class="footer">')
    else:
        content = base_html + inject

    # Provenance
    provenance: list[dict[str, Any]] = []
    for h in trend.get("provenance") or []:
        provenance.append(h)
    for h in (avt or {}).get("provenance") or []:
        provenance.append(h)
    for h in (compare or {}).get("provenance") or []:
        provenance.append(h)
    for f in facts[:50]:
        provenance.append(
            {
                "entity": f.entity,
                "metric": f.metric,
                "value": f.value,
                "unit": f.unit,
                "period": f.fiscal_year,
                "document_id": f.document_id,
                "document_name": f.document_name,
                "page": f.page,
                "fact_id": f.chunk_id,
                "domain": "mining",
            }
        )
    for e in (geo_payload.get("evidence") or [])[:80]:
        provenance.append({**e, "domain": "geological"})

    reports_dir = documents_root() / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    mining_fact_dicts = [
        {
            "entity": f.entity,
            "metric": f.metric,
            "value": f.value,
            "unit": f.unit,
            "fiscal_year": f.fiscal_year,
            "document_id": f.document_id,
            "document_name": f.document_name,
            "page": f.page,
            "fact_id": f.chunk_id,
            "status": "verified_structured",
        }
        for f in facts
    ]
    conflict_dicts = [
        {
            "entity_name": c.entity_name,
            "field_name": c.field_name,
            "period": c.period,
            "severity": c.severity,
            "status": c.status,
            "description": c.description,
        }
        for c in conflicts
    ]

    params: dict[str, Any] = {
        "domain": domain_l,
        "entity": entity,
        "metric": metric,
        "period": period,
        "document_ids": document_ids or [],
        "source_documents": source_docs,
        "compare_entities": peers[:6],
        "trend_points": len(trend.get("data") or []),
        "fact_count": len(facts),
        "geo_fact_count": len(geo_payload.get("geological_facts") or []),
        "open_conflicts": len(conflicts),
        "review_required_count": geo_payload.get("review_required_count") or 0,
        "rejected_excluded": geo_payload.get("rejected_excluded") or 0,
        "pending_verification": bool(geo_payload.get("review_required_count")),
        "warnings": geo_payload.get("warnings") or [],
        "format": "html",
        "generated_at": generated_at,
        "disclaimer": DISCLAIMER,
        "insufficient": bool(
            include_mining
            and trend.get("insufficient")
            and (not avt or avt.get("insufficient"))
            and not facts
            and not (geo_payload.get("geological_facts") or geo_payload.get("resources"))
        ),
        "export_bundle": {
            "mining_facts": mining_fact_dicts[:500],
            "geological_facts": (geo_payload.get("geological_facts") or [])[:500],
            "conflicts": conflict_dicts[:200],
            "evidence": (geo_payload.get("evidence") or [])[:500],
            "resources": (geo_payload.get("resources") or [])[:200],
        },
    }

    report = Report(
        title=report_title,
        report_type=report_type if report_type != "summary" else domain_l,
        content=content,
        status="ready",
        generated_by=generated_by,
        created_by_user_id=created_by_user_id
        if created_by_user_id and created_by_user_id != "anonymous"
        else None,
        source_document_ids=document_ids or [],
        selected_entities=[entity] if entity else peers[:6],
        selected_periods=[period] if period else [],
        output_format="html",
        provenance=provenance,
        parameters=params,
    )
    db.add(report)
    db.flush()

    out_path = reports_dir / f"{report.id}.html"
    out_path.write_text(content, encoding="utf-8")
    report.output_path = str(out_path.resolve())
    db.commit()
    db.refresh(report)
    return report


def export_report_pdf(db: Session, report: Report) -> Path:
    reports_dir = documents_root() / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = reports_dir / f"{report.id}.pdf"
    params = report.parameters if isinstance(report.parameters, dict) else {}
    write_report_pdf(
        title=report.title or "MineIntel Report",
        html_content=report.content or "",
        output_path=pdf_path,
        meta={
            "generated_at": params.get("generated_at"),
            "domain": params.get("domain") or report.report_type,
            "warnings": params.get("warnings") or [],
        },
    )
    return pdf_path


def export_report_excel(db: Session, report: Report) -> Path:
    reports_dir = documents_root() / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = reports_dir / f"{report.id}.xlsx"
    params = report.parameters if isinstance(report.parameters, dict) else {}
    bundle = params.get("export_bundle") or {}
    write_report_excel(
        output_path=xlsx_path,
        summary={
            "title": report.title,
            "domain": params.get("domain") or report.report_type,
            "report_type": report.report_type,
            "generated_at": params.get("generated_at"),
            "generated_by": report.generated_by,
            "source_documents": params.get("source_documents") or [],
            "fact_count": params.get("fact_count"),
            "geo_fact_count": params.get("geo_fact_count"),
            "open_conflicts": params.get("open_conflicts"),
            "review_required_count": params.get("review_required_count"),
            "rejected_excluded": params.get("rejected_excluded"),
            "pending_verification": params.get("pending_verification"),
            "disclaimer": params.get("disclaimer") or DISCLAIMER,
            "warnings": params.get("warnings") or [],
        },
        mining_facts=bundle.get("mining_facts"),
        geological_facts=bundle.get("geological_facts"),
        conflicts=bundle.get("conflicts"),
        evidence=bundle.get("evidence"),
        resources=bundle.get("resources"),
    )
    return xlsx_path
