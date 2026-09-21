"""PDF export for MineIntel reports using PyMuPDF (no cloud APIs)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import fitz


def _plain_from_html(html: str) -> str:
    """Lightweight HTML → text for PDF layout (no external renderer)."""
    text = html or ""
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6]|li|section)>", "\n", text)
    text = re.sub(r"(?i)<th[^>]*>", " | ", text)
    text = re.sub(r"(?i)<td[^>]*>", " | ", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def write_report_pdf(
    *,
    title: str,
    html_content: str,
    output_path: Path,
    meta: Optional[dict[str, Any]] = None,
) -> Path:
    """Create a multi-page PDF with title, body text, and page numbers."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    body = _plain_from_html(html_content)
    meta = meta or {}

    header_lines = [
        "MineIntel AI — Intelligence Report",
        title,
        f"Generated: {meta.get('generated_at') or ''}",
        f"Domain: {meta.get('domain') or meta.get('report_type') or 'report'}",
        f"Status legend: VERIFIED | REVIEW REQUIRED | REJECTED/EXCLUDED",
        "",
        "Disclaimer: Values come from extracted/verified structured evidence. "
        "Review-required items are pending human verification. "
        "Rejected facts are excluded. Numbers are not invented by the LLM.",
        "",
    ]
    if meta.get("warnings"):
        header_lines.append("Warnings:")
        for w in meta["warnings"][:12]:
            header_lines.append(f"  - {w}")
        header_lines.append("")

    full_text = "\n".join(header_lines) + body
    if not full_text.strip():
        full_text = "Insufficient compatible evidence was available for this report."

    doc = fitz.open()
    margin = 48
    fontsize = 10
    line_height = 13
    page_width, page_height = fitz.paper_size("a4")
    usable_height = page_height - 2 * margin - 24
    lines_per_page = max(20, int(usable_height / line_height))

    # Word-wrap
    wrapped: list[str] = []
    max_chars = 95
    for raw_line in full_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            wrapped.append("")
            continue
        while len(line) > max_chars:
            cut = line.rfind(" ", 0, max_chars)
            if cut < 40:
                cut = max_chars
            wrapped.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        wrapped.append(line)

    for i in range(0, len(wrapped), lines_per_page):
        chunk = wrapped[i : i + lines_per_page]
        page = doc.new_page(width=page_width, height=page_height)
        y = margin
        page.insert_text(
            fitz.Point(margin, y),
            "MineIntel AI",
            fontsize=11,
            fontname="helv",
            color=(0.78, 0.52, 0.23),
        )
        y += 18
        for line in chunk:
            if y > page_height - margin - 16:
                break
            page.insert_text(
                fitz.Point(margin, y),
                line[:120],
                fontsize=fontsize,
                fontname="cour",
                color=(0.1, 0.1, 0.1),
            )
            y += line_height
        page_no = len(doc)
        page.insert_text(
            fitz.Point(page_width / 2 - 20, page_height - 28),
            f"Page {page_no}",
            fontsize=9,
            fontname="helv",
            color=(0.4, 0.4, 0.4),
        )

    if len(doc) == 0:
        page = doc.new_page(width=page_width, height=page_height)
        page.insert_text(
            fitz.Point(margin, margin),
            "Empty report — insufficient evidence.",
            fontsize=12,
            fontname="helv",
        )

    doc.set_metadata(
        {
            "title": title[:200],
            "author": "MineIntel AI",
            "subject": "Evidence-grounded mining / geological report",
            "creator": "MineIntel AI Phase 7",
        }
    )
    doc.save(str(output_path))
    doc.close()
    return output_path
