"""Geological report sections — structured GeologicalFact only (no invented numbers)."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.geology import explorer as geo_explorer
from app.geology import geo_analytics
from app.geology.explorer import REJECTED_STATUS, VERIFIED_STATUSES
from app.models import Document, FactStatus, GeologicalFact
from app.reports.html import esc


DISCLAIMER = (
    "Generated analysis is based on available extracted and verified evidence from "
    "selected documents. Review-required values are pending human verification and "
    "must not be treated as verified. Rejected facts are excluded. "
    "The LLM was not used as a source of numerical truth."
)


def _status_label(status: Optional[str]) -> str:
    s = (status or "").lower()
    if s in VERIFIED_STATUSES:
        return "VERIFIED"
    if s == FactStatus.REJECTED.value:
        return "REJECTED / EXCLUDED"
    return "REVIEW REQUIRED"


def _badge(status: Optional[str]) -> str:
    label = _status_label(status)
    if label == "VERIFIED":
        cls = "ok"
    elif label.startswith("REJECTED"):
        cls = "empty"
    else:
        cls = "empty"
    return f'<span class="chip">{esc(label)}</span>'


def collect_geological_payload(
    db: Session,
    *,
    document_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Assemble geological report data from structured facts only."""
    docs: list[Document] = []
    if document_ids:
        docs = db.query(Document).filter(Document.id.in_(document_ids)).all()
    else:
        geo_docs = geo_explorer.list_geological_documents(db)
        ids = [d["document_id"] for d in geo_docs if d.get("document_id")]
        if ids:
            docs = db.query(Document).filter(Document.id.in_(ids)).all()

    summaries = []
    formations = []
    seams = []
    boreholes = []
    resources = []
    thickness = []
    geo_facts = []
    evidence = []
    warnings: list[str] = []
    review_required_count = 0
    rejected_excluded = 0

    for doc in docs:
        summary = geo_explorer.document_summary(db, doc.id)
        summaries.append(summary)
        if summary.get("pending_verification"):
            warnings.append(
                f"{summary.get('document_name')}: structured geological facts pending human verification."
            )
        review_required_count += int(summary.get("review_required_count") or 0)

        formations.extend(
            geo_explorer.list_formations(db, document_id=doc.id)
        )
        seams.extend(geo_explorer.list_seams(db, document_id=doc.id))
        boreholes.extend(geo_explorer.list_boreholes(db, document_id=doc.id))

        res = geo_analytics.resources_by_seam(db, document_id=doc.id)
        resources.extend(res.get("items") or [])
        if res.get("pending_verification"):
            warnings.append(
                f"{summary.get('document_name')}: resource analytics pending verification."
            )
        if res.get("empty"):
            warnings.append(
                f"{summary.get('document_name')}: no compatible resource evidence."
            )

        thick = geo_analytics.seam_thickness_analytic(db, document_id=doc.id)
        thickness.extend(thick.get("items") or [])
        if thick.get("empty"):
            warnings.append(
                f"{summary.get('document_name')}: no compatible seam-thickness evidence."
            )

        rows = (
            db.query(GeologicalFact)
            .filter(GeologicalFact.document_id == doc.id)
            .order_by(GeologicalFact.source_page, GeologicalFact.created_at)
            .all()
        )
        for row in rows:
            if row.status == REJECTED_STATUS:
                rejected_excluded += 1
                continue
            item = geo_explorer.fact_to_explorer_item(row, doc)
            geo_facts.append(item)
            evidence.append(
                {
                    "fact_id": row.id,
                    "document_id": doc.id,
                    "document_name": doc.original_filename or doc.filename,
                    "page": row.source_page,
                    "status": row.status,
                    "status_label": _status_label(row.status),
                    "metric_kind": item.get("metric_kind"),
                    "value": item.get("display_value"),
                    "unit": item.get("display_unit"),
                    "evidence_text": (row.evidence_text or "")[:500],
                    "seam": item.get("seam_label"),
                    "formation": item.get("formation_name"),
                    "borehole_id": row.borehole_id,
                }
            )

    # Deduplicate formations by name+document
    seen_f = set()
    uniq_formations = []
    for f in formations:
        key = (f.get("formation_name"), tuple(f.get("documents") or []))
        if key in seen_f:
            continue
        seen_f.add(key)
        uniq_formations.append(f)

    return {
        "documents": [
            {
                "document_id": d.id,
                "document_name": d.original_filename or d.filename,
                "version": d.version or 1,
                "document_type": d.document_category,
                "page_count": d.page_count,
            }
            for d in docs
        ],
        "summaries": summaries,
        "formations": uniq_formations,
        "seams": seams,
        "boreholes": boreholes,
        "resources": resources,
        "seam_thickness": thickness,
        "geological_facts": geo_facts[:500],
        "evidence": evidence[:500],
        "warnings": sorted(set(warnings)),
        "review_required_count": review_required_count,
        "rejected_excluded": rejected_excluded,
        "disclaimer": DISCLAIMER,
    }


def build_geological_html_sections(payload: dict[str, Any]) -> str:
    parts: list[str] = []

    parts.append('<section class="section"><h3>Geological document summary</h3>')
    if not payload.get("summaries"):
        parts.append('<p class="empty">No geological documents / structured facts selected.</p>')
    else:
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Document</th><th>Type</th><th>Facts</th><th>Formations</th>"
            "<th>Seams</th><th>Boreholes</th><th>Resources</th><th>Review required</th>"
            "</tr></thead><tbody>"
        )
        for s in payload["summaries"]:
            parts.append(
                "<tr>"
                f"<td>{esc(s.get('document_name'))}</td>"
                f"<td>{esc(s.get('document_type'))}</td>"
                f"<td class='num'>{esc(s.get('fact_count'))}</td>"
                f"<td class='num'>{esc(s.get('formation_count'))}</td>"
                f"<td class='num'>{esc(s.get('seam_count'))}</td>"
                f"<td class='num'>{esc(s.get('borehole_count'))}</td>"
                f"<td class='num'>{esc(s.get('resource_fact_count'))}</td>"
                f"<td class='num'>{esc(s.get('review_required_count'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    if payload.get("warnings"):
        parts.append('<section class="section"><h3>Warnings</h3><ul>')
        for w in payload["warnings"][:40]:
            parts.append(f"<li>{esc(w)}</li>")
        parts.append("</ul></section>")

    parts.append('<section class="section"><h3>Formations</h3>')
    if not payload.get("formations"):
        parts.append('<p class="empty">No compatible formation evidence available.</p>')
    else:
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Formation</th><th>Associated seams</th><th>Pages</th>"
            "<th>Evidence count</th><th>Status</th>"
            "</tr></thead><tbody>"
        )
        for f in payload["formations"]:
            parts.append(
                "<tr>"
                f"<td>{esc(f.get('formation_name'))}</td>"
                f"<td>{esc(', '.join(f.get('associated_seams') or []))}</td>"
                f"<td>{esc(', '.join(str(p) for p in (f.get('source_pages') or [])))}</td>"
                f"<td class='num'>{esc(f.get('evidence_count'))}</td>"
                f"<td>{_badge('approved' if f.get('review_status')=='verified' else 'review_required')}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    parts.append('<section class="section"><h3>Seams</h3>')
    if not payload.get("seams"):
        parts.append('<p class="empty">No compatible seam evidence available.</p>')
    else:
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Seam</th><th>Formation</th><th>Thickness</th><th>Resource</th>"
            "<th>Pages</th><th>Status</th><th>Document</th>"
            "</tr></thead><tbody>"
        )
        for s in payload["seams"]:
            thick = s.get("thickness")
            thick_s = f"{thick} {s.get('thickness_unit') or ''}".strip() if thick else "—"
            res = s.get("resource")
            res_s = f"{res} {s.get('resource_unit') or ''}".strip() if res else "—"
            parts.append(
                "<tr>"
                f"<td>{esc(s.get('seam_name'))}</td>"
                f"<td>{esc(s.get('formation') or '—')}</td>"
                f"<td class='num'>{esc(thick_s)}</td>"
                f"<td class='num'>{esc(res_s)}</td>"
                f"<td>{esc(', '.join(str(p) for p in (s.get('source_pages') or [])))}</td>"
                f"<td>{_badge('approved' if s.get('review_status')=='verified' else 'review_required')}</td>"
                f"<td>{esc(s.get('document_name'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    parts.append('<section class="section"><h3>Resource by seam</h3>')
    if not payload.get("resources"):
        parts.append('<p class="empty">No compatible structured resource evidence available.</p>')
    else:
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Seam</th><th>Value</th><th>Unit</th><th>Page</th>"
            "<th>Status</th><th>Document</th><th>Fact ID</th>"
            "</tr></thead><tbody>"
        )
        for r in payload["resources"]:
            parts.append(
                "<tr>"
                f"<td>{esc(r.get('seam'))}</td>"
                f"<td class='num'>{esc(r.get('value'))}</td>"
                f"<td>{esc(r.get('unit') or '')}</td>"
                f"<td>{esc(r.get('page') if r.get('page') is not None else '')}</td>"
                f"<td>{_badge(r.get('status'))}</td>"
                f"<td>{esc(r.get('document_name'))}</td>"
                f"<td>{esc((r.get('fact_id') or '')[:12])}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    parts.append('<section class="section"><h3>Compatible seam thickness</h3>')
    if not payload.get("seam_thickness"):
        parts.append(
            '<p class="empty">No compatible seam-thickness evidence available. '
            "Minimum workable / formation / parting thickness are not substituted.</p>"
        )
    else:
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Seam</th><th>Value</th><th>Unit</th><th>Page</th><th>Status</th><th>Document</th>"
            "</tr></thead><tbody>"
        )
        for t in payload["seam_thickness"]:
            parts.append(
                "<tr>"
                f"<td>{esc(t.get('seam'))}</td>"
                f"<td class='num'>{esc(t.get('value'))}</td>"
                f"<td>{esc(t.get('unit') or '')}</td>"
                f"<td>{esc(t.get('page') if t.get('page') is not None else '')}</td>"
                f"<td>{_badge(t.get('status'))}</td>"
                f"<td>{esc(t.get('document_name'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    parts.append('<section class="section"><h3>Boreholes</h3>')
    if not payload.get("boreholes"):
        parts.append('<p class="empty">No compatible borehole evidence available.</p>')
    else:
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Borehole</th><th>Depth</th><th>Seams</th><th>Pages</th><th>Status</th><th>Document</th>"
            "</tr></thead><tbody>"
        )
        for b in payload["boreholes"]:
            depth = b.get("depth")
            depth_s = f"{depth} {b.get('depth_unit') or ''}".strip() if depth else "—"
            parts.append(
                "<tr>"
                f"<td>{esc(b.get('borehole_id'))}</td>"
                f"<td class='num'>{esc(depth_s)}</td>"
                f"<td>{esc(', '.join(b.get('associated_seams') or []))}</td>"
                f"<td>{esc(', '.join(str(p) for p in (b.get('source_pages') or [])))}</td>"
                f"<td>{_badge('approved' if b.get('review_status')=='verified' else 'review_required')}</td>"
                f"<td>{esc(b.get('document_name'))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    parts.append('<section class="section"><h3>Geological evidence / sources</h3>')
    evid = payload.get("evidence") or []
    if not evid:
        parts.append('<p class="empty">No geological evidence rows.</p>')
    else:
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Fact ID</th><th>Metric</th><th>Value</th><th>Status</th>"
            "<th>Document</th><th>Page</th><th>Evidence</th>"
            "</tr></thead><tbody>"
        )
        for e in evid[:80]:
            parts.append(
                "<tr>"
                f"<td>{esc((e.get('fact_id') or '')[:12])}</td>"
                f"<td>{esc(e.get('metric_kind') or '')}</td>"
                f"<td class='num'>{esc(e.get('value'))} {esc(e.get('unit') or '')}</td>"
                f"<td>{_badge(e.get('status'))}</td>"
                f"<td>{esc(e.get('document_name'))}</td>"
                f"<td>{esc(e.get('page') if e.get('page') is not None else '')}</td>"
                f"<td>{esc((e.get('evidence_text') or '')[:160])}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append(
        f"<p class='footer' style='border:none;margin-top:12px'>{esc(payload.get('disclaimer') or DISCLAIMER)}</p>"
    )
    parts.append("</section>")

    if payload.get("rejected_excluded"):
        parts.append(
            f'<section class="section"><h3>Excluded data</h3>'
            f'<p class="empty">{esc(payload["rejected_excluded"])} rejected geological fact(s) '
            f"were excluded from this report.</p></section>"
        )

    return "\n".join(parts)
