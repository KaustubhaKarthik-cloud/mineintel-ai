"""Header-first structured table extraction (generic, no org/document hard-codes).

Uses PDF table geometry (PyMuPDF find_tables) to bind each cell to its
row label + column header hierarchy before any LLM sees the numbers.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional
from uuid import uuid5, NAMESPACE_URL

from app.retrieval.chunker import ChunkDraft
from app.retrieval.table_reconstruct import normalize_month_token


@dataclass
class StructuredFact:
    entity: str
    metric: str
    reporting_month: Optional[str]
    fiscal_year: str
    measurement_type: str  # during | upto | target | actual | unknown
    value: float
    unit: str
    page: int
    table_id: str
    table_title: str
    row_label: str
    column_path: str
    confidence: float
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_evidence_text(self) -> str:
        month = self.reporting_month or "Unknown"
        return (
            f"STRUCTURED_FACT | entity={self.entity} | metric={self.metric} | "
            f"reporting_period={month} | measure={self.measurement_type} | "
            f"fiscal_year={self.fiscal_year} | value={self.value:g} | unit={self.unit} | "
            f"table={self.table_title or self.table_id} | page={self.page} | "
            f"column={self.column_path}"
        )

    def to_meta(self) -> dict[str, Any]:
        d = asdict(self)
        return d


_FY_RE = re.compile(r"\bFY\s*([’'`\"]?\s*)?(20)?(\d{2})\b", re.I)
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _clean_cell(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_number(cell: str) -> Optional[float]:
    if not cell:
        return None
    # Prefer first decimal-looking token (handles "85.81 9" OCR glue)
    m = re.search(r"-?\d+\.\d{1,3}", cell)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    m = re.search(r"-?\d+", cell)
    if not m:
        return None
    # skip pure integers that look like serials when alone and tiny — still allow 0
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _norm_fy(token: str) -> Optional[str]:
    m = _FY_RE.search(token or "")
    if not m:
        return None
    return f"FY20{m.group(3)}"


def _fy_from_month_year_header(text: str) -> Optional[str]:
    """Map 'Mar' 2025' / 'March 2024' headers to FY20YY (MoC calendar-year month labels)."""
    m = re.search(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s*['’]?\s*(?:20)?(\d{2})\b",
        text or "",
        re.I,
    )
    if not m:
        return None
    return f"FY20{m.group(1)}"


def _detect_unit(title: str, headers: str) -> str:
    blob = f"{title} {headers}".lower()
    if "m.cum" in blob or "mcum" in blob:
        return "M.Cum"
    if "(mu)" in blob or " mu" in blob or "million unit" in blob or "kwh" in blob:
        return "MU"
    if "mt" in blob or "tonne" in blob:
        return "MT"
    return "MT"


def _detect_metric(title: str) -> Optional[str]:
    t = (title or "").lower()
    if "lignite" in t:
        return "lignite"
    if "overburden" in t or re.search(r"\bobr\b", t):
        return "overburden"
    if "coking" in t and "coal" in t:
        return "coking_coal"
    if "power" in t or "generation" in t or "(mu)" in t or "thermal power" in t:
        return "power_generation"
    if "productivity" in t:
        return "productivity"
    if "coal" in t and "production" in t:
        return "coal"
    if "coal" in t and "dispatch" in t:
        return "dispatch"
    if "production" in t and "coal" not in t and "lignite" not in t:
        # ambiguous production — refuse rather than invent coal
        return None
    return None


def _month_from_text(text: str) -> Optional[str]:
    m = re.search(
        r"(?:during|upto|up\s*to|in)\s+"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b",
        text or "",
        re.I,
    )
    if m:
        return normalize_month_token(m.group(1))
    m = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s*['’]?\s*(?:20)?\d{2}\b",
        text or "",
        re.I,
    )
    if m:
        return normalize_month_token(m.group(1))
    return None


def _classify_column(header_top: str, header_sub: str) -> dict[str, Optional[str]]:
    """Map a column's header stack to semantic roles (generic, layout-agnostic)."""
    top = (header_top or "").lower()
    sub = (header_sub or "").lower()
    joined = f"{top} {sub}".strip()
    out: dict[str, Optional[str]] = {
        "role": None,
        "fiscal_year": _norm_fy(joined) or _fy_from_month_year_header(joined),
        "measurement_type": None,
        "reporting_month": _month_from_text(joined),
    }
    if re.search(
        r"\bsl\b|\bs\.?\s*no\b|subs|company|state|source|mode of",
        joined,
    ) and not re.search(r"fy\s*\d|during|upto|target|actual|mar['’]?\s*\d", joined):
        out["role"] = "label"
        return out

    # Target under a during/upto parent is still a target, not the actual production.
    if "target" in sub or ( "target" in top and "actual" not in joined):
        if "ach" not in joined:
            out["role"] = "value"
            out["measurement_type"] = "target"
            return out

    if re.search(r"achmt|achvm|achiev", joined):
        out["role"] = "achievement"
        return out
    if "growth" in joined:
        out["role"] = "growth"
        return out

    # During Mar' 2025 / Actual → during production for that FY
    if "during" in top or "during" in sub:
        if "actual" in joined:
            out["measurement_type"] = "during"
            out["role"] = "value"
            return out
        # Bare during parent with no sub-role yet (FY already known)
        if out["fiscal_year"] and "target" not in sub and "ach" not in sub:
            out["measurement_type"] = "during"
            out["role"] = "value"
            return out

    # Prior-year month column: "Mar' 2024" (no During/Upto keyword)
    if (
        out["fiscal_year"]
        and out["reporting_month"]
        and "upto" not in top
        and "during" not in top
        and re.search(
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
            top,
            re.I,
        )
    ):
        out["measurement_type"] = "during"
        out["role"] = "value"
        return out

    if re.search(r"\bupto\b|\bup\s*to\b", top) or re.search(r"\bupto\b|\bup\s*to\b", sub):
        out["measurement_type"] = "upto"
        out["role"] = "value"
        return out

    if out["fiscal_year"] and ("fy" in sub or "fy" in top):
        out["role"] = "value"
        if not out["measurement_type"]:
            if "during" in top:
                out["measurement_type"] = "during"
            elif re.search(r"upto|up\s*to", top):
                out["measurement_type"] = "upto"
        return out

    if out["role"] is None and out["fiscal_year"] and out["measurement_type"]:
        out["role"] = "value"
    return out


def _forward_fill_headers(row: list[str]) -> list[str]:
    out: list[str] = []
    last = ""
    for cell in row:
        c = _clean_cell(cell)
        if c:
            last = c
        out.append(last)
    return out


def _forward_fill_subheaders(top_filled: list[str], sub_row: list[str]) -> list[str]:
    """Forward-fill sub-headers only within the same parent (top) column group."""
    out: list[str] = []
    last = ""
    last_top = None
    for i, cell in enumerate(sub_row):
        top = top_filled[i] if i < len(top_filled) else ""
        if top != last_top:
            last = ""
            last_top = top
        c = _clean_cell(cell)
        if c:
            last = c
        out.append(last)
    return out


def _entity_from_row(row: list[str], label_cols: list[int]) -> Optional[str]:
    for i in label_cols:
        if i < len(row):
            lab = _clean_cell(row[i])
            if not lab:
                continue
            if re.fullmatch(r"\d{1,3}", lab):
                continue
            if lab.lower() in {"total", "grand total", "fig. in mt", "qty. in mt"}:
                # still allow CIL / company totals — only skip pure "Total" if needed
                if lab.lower() in {"total"}:
                    continue
            return lab
    # fallback: first non-numeric cell
    for cell in row:
        lab = _clean_cell(cell)
        if lab and not re.fullmatch(r"[\d.▲▼%\s]+", lab):
            if not re.fullmatch(r"\d{1,3}", lab):
                return lab
    return None


def parse_table_matrix(
    matrix: list[list[Any]],
    *,
    page: int,
    table_index: int,
    page_text: str = "",
    table_title: str = "",
) -> list[StructuredFact]:
    """Parse an extracted table matrix into structured facts."""
    if not matrix or len(matrix) < 3:
        return []
    rows = [[_clean_cell(c) for c in row] for row in matrix]
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]

    # Detect header depth: first rows with FY / during / upto cues
    header_rows = 0
    for i, r in enumerate(rows[:3]):
        joined = " ".join(r).lower()
        if re.search(r"fy\s*\d|during|upto|target|achmt|subs|sl\s*no|company|state", joined):
            header_rows = i + 1
        else:
            break
    if header_rows == 0:
        return []

    top = _forward_fill_headers(rows[0])
    sub = (
        _forward_fill_subheaders(top, rows[1])
        if header_rows >= 2
        else [""] * ncol
    )
    if header_rows >= 3:
        sub2 = _forward_fill_subheaders(top, rows[2])
        sub = [f"{a} {b}".strip() for a, b in zip(sub, sub2)]

    # Prefer the caller-provided local title (clip above this table).
    # Do NOT steal another table's caption from elsewhere on the page.
    title = (table_title or "").strip()
    metric = _detect_metric(title) or _detect_metric(" ".join(top) + " " + " ".join(sub))
    if not metric:
        # Nearby caption only — never borrow metric from unrelated tables on the page.
        m = re.search(
            r"(Table\s+[\d.]+[^\n]{0,120}(?:Coal|Lignite|Production|Dispatch|Power|Overburden)[^\n]{0,60})",
            page_text or "",
            re.I,
        )
        if m:
            alt = m.group(1).strip()
            # Only accept if this caption is compatible with our local title fragment
            if not title or title.lower()[:20] in alt.lower() or alt.lower()[:20] in (title or "").lower():
                metric = _detect_metric(alt)
                if metric and not title:
                    title = alt
    if not metric:
        # Refuse rather than invent coal/lignite from distant page text
        return []

    unit = _detect_unit(title, " ".join(top) + " " + " ".join(sub))
    if unit == "MT" and metric == "power_generation":
        unit = "MU"
    page_month = _month_from_text(" ".join(top) + " " + " ".join(sub)) or _month_from_text(
        page_text
    ) or _month_from_text(title)

    col_meta: list[dict[str, Optional[str]]] = []
    label_cols: list[int] = []
    for c in range(ncol):
        meta = _classify_column(top[c] if c < len(top) else "", sub[c] if c < len(sub) else "")
        col_meta.append(meta)
        if meta["role"] == "label":
            label_cols.append(c)
    if not label_cols:
        label_cols = [0, 1]

    facts: list[StructuredFact] = []
    data_start = header_rows
    table_id = f"p{page}:t{table_index}"

    for ri, row in enumerate(rows[data_start:], start=data_start):
        entity = _entity_from_row(row, label_cols)
        if not entity:
            continue
        if entity.lower() in {"fig. in mt", "qty. in mt", "sl no", "subs"}:
            continue
        # Row label may refine metric (e.g. "Coal Production (MT)" inside a lignite table)
        row_metric = _detect_metric(entity) or metric
        row_unit = unit
        if row_metric == "power_generation" and row_unit == "MT":
            row_unit = "MU"
        if "kwh" in entity.lower() or "(mu)" in entity.lower():
            row_metric = "power_generation"
            row_unit = "MU"
        for ci, cell in enumerate(row):
            meta = col_meta[ci]
            if meta.get("role") != "value":
                continue
            if not meta.get("fiscal_year"):
                continue
            measure = meta.get("measurement_type") or "unknown"
            if measure == "unknown":
                continue
            month = meta.get("reporting_month") or page_month
            if measure in {"during", "upto"} and not month:
                continue
            num = _parse_number(cell)
            if num is None:
                continue
            # Refuse absurd MT magnitudes (likely MU / wrong table binding)
            if row_metric in {"coal", "lignite", "coking_coal"} and row_unit == "MT" and num > 5000:
                continue
            col_path = " / ".join(
                x for x in [top[ci] if ci < len(top) else "", sub[ci] if ci < len(sub) else ""] if x
            )
            conf = 0.9 if month and meta.get("fiscal_year") and measure != "unknown" else 0.6
            facts.append(
                StructuredFact(
                    entity=entity,
                    metric=row_metric,
                    reporting_month=month,
                    fiscal_year=meta["fiscal_year"] or "",
                    measurement_type=measure,
                    value=num,
                    unit=row_unit,
                    page=page,
                    table_id=table_id,
                    table_title=title,
                    row_label=entity,
                    column_path=col_path,
                    confidence=conf,
                    provenance={
                        "row_index": ri,
                        "col_index": ci,
                        "cell_raw": cell,
                        "header_top": top[ci] if ci < len(top) else "",
                        "header_sub": sub[ci] if ci < len(sub) else "",
                    },
                )
            )
    return facts


def extract_facts_from_pdf_page(pdf_path: Path, page_number: int) -> list[StructuredFact]:
    """Extract structured facts for one 1-based page using table geometry."""
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        if page_number < 1 or page_number > len(doc):
            return []
        page = doc[page_number - 1]
        page_text = page.get_text("text") or ""
        facts: list[StructuredFact] = []
        try:
            finder = page.find_tables()
            tables = list(finder.tables) if finder else []
        except Exception:
            tables = []
        for ti, tab in enumerate(tables):
            try:
                matrix = tab.extract()
            except Exception:
                continue
            # Title cue: text immediately above table bbox (prefer "Table N.N ..." lines)
            title = ""
            try:
                y0 = tab.bbox[1]
                clip = fitz.Rect(0, max(0, y0 - 80), page.rect.width, y0)
                blob = (page.get_text("text", clip=clip) or "").strip()
                m = re.search(
                    r"Table\s+[\d.]+[^\n]{0,120}",
                    blob,
                    re.I,
                )
                if m:
                    title = m.group(0).strip()
                else:
                    # last non-empty line above the table
                    lines = [ln.strip() for ln in blob.splitlines() if ln.strip()]
                    title = lines[-1] if lines else ""
            except Exception:
                title = ""
            facts.extend(
                parse_table_matrix(
                    matrix,
                    page=page_number,
                    table_index=ti,
                    page_text=page_text,
                    table_title=title,
                )
            )
        return facts
    finally:
        doc.close()


def facts_to_chunk_drafts(
    facts: list[StructuredFact],
    *,
    document_id: str,
    document_name: str,
    document_version: int,
    page_id_by_number: dict[int, Optional[str]],
    start_index: int = 0,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for i, fact in enumerate(facts):
        text = fact.to_evidence_text()
        key = (
            f"struct:v{document_version}:p{fact.page}:{fact.table_id}:"
            f"{fact.entity}:{fact.metric}:{fact.reporting_month}:{fact.measurement_type}:"
            f"{fact.fiscal_year}:{fact.value}"
        )
        drafts.append(
            ChunkDraft(
                chunk_id=str(uuid5(NAMESPACE_URL, f"mineintel:{document_id}:{key}")),
                chunk_index=start_index + i,
                text=text,
                document_page_id=page_id_by_number.get(fact.page),
                page_number=fact.page,
                sheet_name=None,
                source_type="pdf_table",
                source_location=f"page {fact.page} / {fact.table_id} / {fact.column_path}",
                content_type="structured_fact",
                document_name=document_name,
                document_version=document_version,
                token_count=len(text.split()),
                meta={**fact.to_meta(), "structured_fact": True},
            )
        )
    return drafts
