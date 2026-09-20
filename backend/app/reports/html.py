"""Styled HTML builders for MineIntel reports."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Optional


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


REPORT_CSS = """
:root {
  --bg: #121816; --panel: #1a221e; --panel-2: #222c27; --border: #3a4a42;
  --text: #e6efe9; --muted: #8a9e92; --copper: #c8843a; --green: #5fad7a; --amber: #d4a017;
}
* { box-sizing: border-box; }
body {
  margin: 0; font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  background: radial-gradient(1200px 600px at 10% -10%, #24302a 0%, var(--bg) 55%);
  color: var(--text); line-height: 1.5; min-height: 100vh;
}
.wrap { max-width: 960px; margin: 0 auto; padding: 32px 20px 64px; }
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 28px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
.brand-mark { width: 40px; height: 40px; border-radius: 8px; background: #1c2420; border: 1px solid rgba(200,132,58,.45); display: grid; place-items: center; color: var(--copper); font-weight: 700; }
.brand h1 { margin: 0; font-size: 18px; letter-spacing: .12em; text-transform: uppercase; }
.brand p { margin: 2px 0 0; font-size: 11px; color: var(--copper); letter-spacing: .18em; text-transform: uppercase; }
.hero { background: linear-gradient(145deg, var(--panel) 0%, var(--panel-2) 100%); border: 1px solid var(--border); border-radius: 12px; padding: 24px 26px; margin-bottom: 20px; }
.hero h2 { margin: 0 0 10px; font-size: 26px; font-weight: 650; }
.meta { color: var(--muted); font-size: 13px; display: flex; flex-wrap: wrap; gap: 8px 16px; }
.meta strong { color: var(--text); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.chip { font-size: 11px; text-transform: uppercase; letter-spacing: .08em; padding: 5px 10px; border-radius: 999px; background: rgba(200,132,58,.12); color: #e0b07a; border: 1px solid rgba(200,132,58,.28); }
.section { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px 20px; margin-bottom: 16px; }
.section h3 { margin: 0 0 12px; font-size: 13px; letter-spacing: .14em; text-transform: uppercase; color: var(--copper); }
.empty { margin: 0; padding: 14px 16px; border-radius: 8px; background: rgba(212,160,23,.08); border: 1px solid rgba(212,160,23,.25); color: #e6c86a; font-size: 14px; }
.ok { margin: 0; padding: 14px 16px; border-radius: 8px; background: rgba(95,173,122,.1); border: 1px solid rgba(95,173,122,.28); color: #b7e0c4; font-size: 14px; }
.ok strong { color: #fff; }
ul.docs { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
ul.docs li { padding: 10px 12px; border-radius: 8px; background: var(--panel-2); border: 1px solid var(--border); font-size: 14px; }
.table-wrap { overflow-x: auto; border-radius: 8px; border: 1px solid var(--border); }
table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 640px; }
th { text-align: left; padding: 10px 12px; background: #16201b; color: var(--muted); font-size: 11px; letter-spacing: .1em; text-transform: uppercase; border-bottom: 1px solid var(--border); }
td { padding: 10px 12px; border-bottom: 1px solid rgba(58,74,66,.7); vertical-align: top; }
tr:last-child td { border-bottom: none; }
.num { color: var(--copper); font-variant-numeric: tabular-nums; font-weight: 600; }
.footer { margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; font-style: italic; }
ul { margin: 0; padding-left: 1.2rem; }
li { margin: 0.35rem 0; }
"""


def wrap_report_document(title: str, body_inner: str, *, generated_at: Optional[str] = None) -> str:
    gen = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{esc(title)} · MineIntel</title>
<style>{REPORT_CSS}</style>
</head>
<body>
  <div class="wrap">
    <header class="brand">
      <div class="brand-mark">MI</div>
      <div>
        <h1>MineIntel AI</h1>
        <p>Verified intelligence report</p>
      </div>
    </header>
    {body_inner}
    <p class="footer">Generated {esc(gen)}. All values are from verified structured facts / indexed table extraction.
    The LLM was not used as a source of numerical truth.</p>
  </div>
</body>
</html>"""


def prefer_entity(entities: list[str], requested: Optional[str]) -> Optional[str]:
    if requested:
        return requested
    if not entities:
        return None
    short = [e for e in entities if 2 <= len(e) <= 12 and e.replace(" ", "").replace("/", "").isalnum()]
    if short:
        caps = [e for e in short if e.isupper()]
        return caps[0] if caps else short[0]
    return entities[0]


def build_summary_html(
    *,
    title: str,
    entity: Optional[str],
    metric: str,
    period: Optional[str],
    trend: dict,
    avt: Optional[dict],
    facts: list,
    source_docs: list[str],
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    chips = []
    if entity:
        chips.append(f'<span class="chip">Entity · {esc(entity)}</span>')
    chips.append(f'<span class="chip">Metric · {esc(metric)}</span>')
    if period:
        chips.append(f'<span class="chip">Period · {esc(period)}</span>')
    if trend.get("unit"):
        chips.append(f'<span class="chip">Unit · {esc(trend.get("unit"))}</span>')

    parts: list[str] = [
        '<section class="hero">',
        f"<h2>{esc(title)}</h2>",
        f'<div class="meta"><span><strong>Generated</strong> {esc(generated)}</span></div>',
        f'<div class="chips">{"".join(chips)}</div>',
        "</section>",
        '<section class="section"><h3>Source documents</h3><ul class="docs">',
    ]
    if source_docs:
        for d in source_docs:
            parts.append(f"<li>{esc(d)}</li>")
    else:
        parts.append("<li>No source documents linked</li>")
    parts.append("</ul></section>")

    parts.append('<section class="section"><h3>Production trends</h3>')
    if trend.get("insufficient"):
        parts.append('<p class="empty">Insufficient verified structured data for this analysis.</p>')
    else:
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Period</th><th>Value</th><th>Unit</th><th>Source</th><th>Page</th>"
            "</tr></thead><tbody>"
        )
        for row in trend.get("data") or []:
            parts.append(
                "<tr>"
                f"<td>{esc(row.get('period') or row.get('year'))}</td>"
                f"<td class='num'>{esc(row.get('value'))}</td>"
                f"<td>{esc(row.get('unit') or '')}</td>"
                f"<td>{esc(row.get('document_name') or '')}</td>"
                f"<td>{esc(row.get('page') if row.get('page') is not None else '')}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    if avt is not None:
        parts.append('<section class="section"><h3>Actual vs target</h3>')
        if avt.get("insufficient"):
            parts.append('<p class="empty">Insufficient verified structured data for this analysis.</p>')
        else:
            parts.append(
                '<p class="ok">'
                f"Actual <strong>{esc(avt.get('actual'))}</strong> {esc(avt.get('unit') or '')}"
                f" · Target <strong>{esc(avt.get('target'))}</strong>"
                f" · Achievement <strong>{esc(avt.get('achievement_percentage'))}%</strong>"
                "</p>"
            )
        parts.append("</section>")

    parts.append('<section class="section"><h3>Cited structured facts</h3>')
    if not facts:
        parts.append('<p class="empty">No structured facts matched the filters.</p>')
    else:
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Entity</th><th>Metric</th><th>Month</th><th>FY</th>"
            "<th>Value</th><th>Unit</th><th>Document</th><th>Page</th><th>Table</th>"
            "</tr></thead><tbody>"
        )
        for f in facts[:80]:
            parts.append(
                "<tr>"
                f"<td>{esc(f.entity)}</td><td>{esc(f.metric)}</td>"
                f"<td>{esc(f.reporting_month or '')}</td><td>{esc(f.fiscal_year or '')}</td>"
                f"<td class='num'>{esc(f.value)}</td><td>{esc(f.unit or '')}</td>"
                f"<td>{esc(f.document_name)}</td>"
                f"<td>{esc(f.page if f.page is not None else '')}</td>"
                f"<td>{esc(f.table_title or f.table_id or '')}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("</section>")

    return wrap_report_document(title, "\n".join(parts), generated_at=generated)


def ensure_styled_html(title: str, content: str) -> str:
    raw = (content or "").strip()
    if not raw:
        return wrap_report_document(title, '<section class="section"><p class="empty">Empty report.</p></section>')
    if "<html" in raw.lower() and "mineintel" in raw.lower() and "--copper" in raw:
        return raw
    if "<html" in raw.lower():
        if "--copper" not in raw and "</head>" in raw.lower():
            return raw.replace("</head>", f"<style>{REPORT_CSS}</style></head>", 1)
        return raw
    return wrap_report_document(title, f'<div class="legacy">{raw}</div>')
