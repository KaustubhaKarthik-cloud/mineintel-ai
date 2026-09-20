"""Phase 7 report builder — verified structured data + provenance (no invented numbers)."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.analytics.index_facts import list_index_facts
from app.analytics.service import actual_vs_target, compare_entities, list_dimensions, year_wise_trend
from app.models import Document, Report
from app.reports.html import build_summary_html, esc, prefer_entity
from app.utils.files import documents_root
from app.validation.service import list_conflicts


def build_full_report(
    db: Session,
    *,
    title: Optional[str] = None,
    report_type: str = "summary",
    entity: Optional[str] = None,
    metric: Optional[str] = None,
    period: Optional[str] = None,
    document_ids: Optional[list[str]] = None,
    compare_entities_list: Optional[list[str]] = None,
    generated_by: str = "ops.analyst",
    created_by_user_id: Optional[str] = None,
) -> Report:
    dims = list_dimensions(db, document_ids=document_ids)
    entity = prefer_entity(dims["entities"], entity)
    metric = metric or (
        "coal" if "coal" in dims["metrics"] else (dims["metrics"][0] if dims["metrics"] else "production")
    )
    if metric == "production" and "coal" in dims["metrics"] and not metric:
        metric = "coal"

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

    report_title = title or f"{entity or 'Mining'} {metric} intelligence report"
    if period:
        report_title = f"{report_title} ({period})"

    base_html = build_summary_html(
        title=report_title,
        entity=entity,
        metric=metric,
        period=period,
        trend=trend,
        avt=avt,
        facts=facts,
        source_docs=source_docs,
    )

    extra_sections: list[str] = []

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
    if not bullets:
        bullets.append(
            "<li>Insufficient verified structured data for a numerical executive summary. "
            "Index documents and verify facts, then regenerate.</li>"
        )
    extra_sections.append("<ul>" + "".join(bullets) + "</ul></section>")

    # Entities covered
    covered = sorted({*(f.entity for f in facts if f.entity), *([entity] if entity else []), *peers[:6]})
    if covered:
        extra_sections.append('<section class="section"><h3>Entities covered</h3><ul class="docs">')
        for e in covered[:40]:
            extra_sections.append(f"<li>{esc(e)}</li>")
        extra_sections.append("</ul></section>")

    if compare and not compare.get("insufficient"):
        extra_sections.append('<section class="section"><h3>Entity comparison</h3>')
        extra_sections.append('<div class="table-wrap"><table><thead><tr>')
        for col in ("Entity", "Value", "Unit", "Period", "Source", "Page"):
            extra_sections.append(f"<th>{col}</th>")
        extra_sections.append("</tr></thead><tbody>")
        for row in compare.get("data") or []:
            extra_sections.append(
                "<tr>"
                f"<td>{esc(row.get('entity'))}</td>"
                f"<td class='num'>{esc(row.get('value'))}</td>"
                f"<td>{esc(row.get('unit') or '')}</td>"
                f"<td>{esc(row.get('period') or '')}</td>"
                f"<td>{esc(row.get('document_name') or '')}</td>"
                f"<td>{esc(row.get('page') if row.get('page') is not None else '')}</td>"
                "</tr>"
            )
        extra_sections.append("</tbody></table></div></section>")

    if conflicts:
        extra_sections.append('<section class="section"><h3>Detected discrepancies / validation</h3>')
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

    # Provenance section from structured facts
    extra_sections.append('<section class="section"><h3>Source provenance</h3>')
    if not facts:
        extra_sections.append('<p class="empty">No provenance rows for the selected filters.</p>')
    else:
        extra_sections.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Entity</th><th>Metric</th><th>Value</th><th>Unit</th>"
            "<th>Document</th><th>Page</th><th>Table</th>"
            "</tr></thead><tbody>"
        )
        for f in facts[:60]:
            extra_sections.append(
                "<tr>"
                f"<td>{esc(f.entity)}</td><td>{esc(f.metric)}</td>"
                f"<td class='num'>{esc(f.value)}</td><td>{esc(f.unit or '')}</td>"
                f"<td>{esc(f.document_name)}</td>"
                f"<td>{esc(f.page if f.page is not None else '')}</td>"
                f"<td>{esc(f.table_title or f.table_id or '')}</td>"
                "</tr>"
            )
        extra_sections.append("</tbody></table></div>")
    extra_sections.append("</section>")

    inject = "\n".join(extra_sections)
    if '<p class="footer">' in base_html:
        content = base_html.replace('<p class="footer">', inject + '\n<p class="footer">')
    else:
        content = base_html + inject

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
                "reporting_month": f.reporting_month,
                "document_id": f.document_id,
                "document_name": f.document_name,
                "page": f.page,
                "table_title": f.table_title,
                "fact_id": f.chunk_id,
            }
        )

    reports_dir = documents_root() / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    report = Report(
        title=report_title,
        report_type=report_type,
        content=content,
        status="ready",
        generated_by=generated_by,
        created_by_user_id=created_by_user_id if created_by_user_id and created_by_user_id != "anonymous" else None,
        source_document_ids=document_ids or [],
        selected_entities=[entity] if entity else peers[:6],
        selected_periods=[period] if period else [],
        output_format="html",
        provenance=provenance,
        parameters={
            "entity": entity,
            "metric": metric,
            "period": period,
            "document_ids": document_ids or [],
            "source_documents": source_docs,
            "compare_entities": peers[:6],
            "trend_points": len(trend.get("data") or []),
            "fact_count": len(facts),
            "open_conflicts": len(conflicts),
            "format": "html",
            "insufficient": bool(trend.get("insufficient") and (not avt or avt.get("insufficient"))),
        },
    )
    db.add(report)
    db.flush()

    out_path = reports_dir / f"{report.id}.html"
    out_path.write_text(content, encoding="utf-8")
    report.output_path = str(out_path.resolve())
    db.commit()
    db.refresh(report)
    return report
