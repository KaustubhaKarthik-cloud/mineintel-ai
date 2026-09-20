"""Paragraph / sentence-aware chunking with source metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from uuid import uuid5, NAMESPACE_URL

from app.config import get_settings
from app.models import Document, DocumentPage, ExtractedFact


@dataclass
class ChunkDraft:
    chunk_id: str
    chunk_index: int
    text: str
    document_page_id: Optional[str]
    page_number: Optional[int]
    sheet_name: Optional[str]
    source_type: Optional[str]
    source_location: Optional[str]
    content_type: str
    document_name: str
    document_version: int
    token_count: int
    meta: dict


def _stable_id(document_id: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"mineintel:{document_id}:{key}"))


def _split_long_text(text: str, size: int, overlap: int) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    # Prefer sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", text)
    buf = ""
    for sent in sentences:
        if not sent:
            continue
        if len(buf) + len(sent) + 1 <= size:
            buf = f"{buf} {sent}".strip()
        else:
            if buf:
                parts.append(buf)
            if len(sent) <= size:
                buf = sent
            else:
                start = 0
                while start < len(sent):
                    end = min(start + size, len(sent))
                    parts.append(sent[start:end])
                    start = max(end - overlap, end if end == len(sent) else end - overlap)
                buf = ""
    if buf:
        parts.append(buf)
    # apply overlap between paragraph chunks if needed
    if overlap > 0 and len(parts) > 1:
        overlapped: list[str] = []
        for i, p in enumerate(parts):
            if i == 0:
                overlapped.append(p)
            else:
                prev_tail = parts[i - 1][-overlap:]
                merged = f"{prev_tail} {p}".strip()
                overlapped.append(merged[: size + overlap])
        return overlapped
    return parts


def _split_by_sections(text: str, size: int, overlap: int) -> list[str]:
    """Prefer numbered report sections so tables stay with their headings."""
    raw = text.strip()
    if not raw:
        return []
    # Split before headings like "18. Production Performance"
    parts = re.split(r"(?=\n\s*\d{1,3}\.\s+[A-Z])", raw)
    pieces: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        pieces.extend(_split_long_text(part, size, overlap))
    return pieces or _split_long_text(raw, size, overlap)


def reconstruct_nlcil_production_block(page_text: str) -> Optional[str]:
    """Rebuild a readable production-performance evidence line from OCR-scrambled tables.

    Typical OCR layout (labels then Actual column then Target column):
      Overburden / Lignite / Coal / Power Gross (NLCIL) / ...
      Actual: <overburden>, <lignite>, <coal>, ...
      Target: <overburden>, <lignite>, <coal>, ...
    """
    if not page_text:
        return None
    compact = re.sub(r"\s+", " ", page_text)
    if not re.search(r"Production Performance\s*\(NLC India", compact, re.I):
        if "NLCIL" not in compact.upper() and "NLC India" not in compact:
            return None
        if not re.search(r"\bLignite\b", compact, re.I):
            return None

    # Prefer the production-performance subsection when present
    m = re.search(
        r"18\.\s*Production Performance\s*\(NLC India\s*Limited\)(.*)$",
        compact,
        re.I | re.S,
    )
    section = m.group(0) if m else compact

    # Prefer decimals that follow Actual / Target labels (avoids profitability noise).
    # Many scans label only "Actual"; the next 7 floats are then the Target column.
    def _nums_after(label: str, limit: int = 14) -> list[float]:
        lm = re.search(rf"\b{label}\b", section, re.I)
        if not lm:
            return []
        return [float(x) for x in re.findall(r"(?<!\()\b(\d+\.\d{2})\b", section[lm.end() :])][:limit]

    after_actual = _nums_after("Actual", 14)
    after_target = _nums_after("Target", 7)
    actual: list[float] = after_actual[:7] if len(after_actual) >= 3 else []
    target: list[float] = after_target[:7] if len(after_target) >= 3 else []
    if len(target) < 3 and len(after_actual) >= 10:
        target = after_actual[7:14]

    if len(actual) < 3 or len(target) < 3:
        # Fallback: last 14 positive decimals (7 actual + 7 target)
        nums = [float(x) for x in re.findall(r"(?<!\()\b(\d+\.\d{2})\b", section)]
        if len(nums) < 8:
            return None
        tail = nums[-14:] if len(nums) >= 14 else nums
        half = len(tail) // 2
        if len(actual) < 3:
            actual = tail[:half]
        if len(target) < 3:
            target = tail[half : half * 2]

    if len(actual) < 3 or len(target) < 3:
        return None
    labels = [
        "Overburden",
        "Lignite",
        "Coal",
        "Power Gross (NLCIL)",
        "Power Export (NLCIL)",
        "Power Gross (NTPL)",
        "Power Export (NTPL)",
    ]
    n = min(len(labels), len(actual), len(target))
    if n < 3:
        return None

    lines = [
        "NLC India Limited (NLCIL) Production Performance for FY 2023-24 "
        "(reconstructed from source table OCR):"
    ]
    for i in range(n):
        lines.append(
            f"{labels[i]}: target {target[i]:.2f}, actual {actual[i]:.2f}."
        )
    lines.append(
        "Evidence source section: Overburden removal, lignite production, "
        "gross power generation and export of power during the year 2023-24."
    )
    return " ".join(lines)


def chunk_document_pages(document: Document, pages: list[DocumentPage]) -> list[ChunkDraft]:
    """Chunk page text only — do NOT invent table semantics from flattened OCR.

    Structured numeric facts are produced separately via header-first PDF table
    geometry during indexing (see structured_table.extract_facts_from_pdf_page).
    """
    settings = get_settings()
    size = settings.chunk_size
    overlap = settings.chunk_overlap
    drafts: list[ChunkDraft] = []
    idx = 0
    for page in sorted(pages, key=lambda p: p.page_number):
        text = (page.text or "").strip()
        if not text:
            continue
        pieces = _split_by_sections(text, size, overlap)

        for i, piece in enumerate(pieces):
            key = f"evidence:v{document.version}:p{page.page_number}:c{i}:{piece[:40]}"
            drafts.append(
                ChunkDraft(
                    chunk_id=_stable_id(document.id, key),
                    chunk_index=idx,
                    text=piece,
                    document_page_id=page.id,
                    page_number=page.page_number,
                    sheet_name=page.sheet_name,
                    source_type=page.source_type,
                    source_location=page.source_location,
                    content_type="document_evidence",
                    document_name=document.original_filename,
                    document_version=document.version or 1,
                    token_count=len(piece.split()),
                    meta={
                        "piece_index": i,
                        "page_id": page.id,
                        "reconstructed_table": False,
                    },
                )
            )
            idx += 1
    return drafts


def chunk_verified_facts(document: Document, facts: list[ExtractedFact]) -> list[ChunkDraft]:
    """Optional secondary index of verified facts (clearly labeled)."""
    drafts: list[ChunkDraft] = []
    idx = 0
    for fact in facts:
        if fact.status not in {"approved", "corrected", "high_confidence"}:
            continue
        if not fact.value:
            continue
        text = (
            f"Verified fact: {fact.field_name} = {fact.value}"
            f"{(' ' + fact.unit) if fact.unit else ''}"
            f"{(' for ' + fact.entity_name) if fact.entity_name else ''}"
            f"{(' (' + fact.financial_year + ')') if fact.financial_year else ''}. "
            f"Evidence: {fact.evidence_text or ''}"
        ).strip()
        key = f"fact:v{document.version}:{fact.id}"
        drafts.append(
            ChunkDraft(
                chunk_id=_stable_id(document.id, key),
                chunk_index=idx,
                text=text,
                document_page_id=fact.document_page_id,
                page_number=fact.page_number,
                sheet_name=fact.sheet_name,
                source_type="verified_fact",
                source_location=fact.source_location,
                content_type="verified_fact",
                document_name=document.original_filename,
                document_version=document.version or 1,
                token_count=len(text.split()),
                meta={"fact_id": fact.id, "field_name": fact.field_name},
            )
        )
        idx += 1
    return drafts
