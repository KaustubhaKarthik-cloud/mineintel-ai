"""Resolve document references and enforce retrieval document scope (generic)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Document, IndexStatus

logger = logging.getLogger("mineintel.document_scope")


@dataclass
class ResolvedDocument:
    document_id: str
    original_filename: str
    match_score: float


@dataclass
class DocumentScope:
    """Resolved retrieval eligibility for a query."""

    mode: str  # single_document | multi_document | cross_document_comparison
    allowed_ids: list[str] = field(default_factory=list)
    primary_id: Optional[str] = None
    primary_name: Optional[str] = None
    reason: str = ""
    rejected_names: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _tokens(s: str) -> list[str]:
    return [t for t in _norm(s).split() if len(t) >= 3]


def filename_key(name: Optional[str]) -> str:
    """Normalize filename for duplicate-family grouping (generic)."""
    base = (name or "").lower().strip()
    base = re.sub(r"\.[a-z0-9]{1,5}$", "", base)
    return _norm(base)


_DEICTIC_RE = re.compile(
    r"(?i)\b("
    r"this\s+(?:exploration\s+)?(?:report|document|pdf|file|block)|"
    r"in\s+this\s+(?:exploration\s+)?(?:report|document|pdf)|"
    r"the\s+current\s+(?:report|document|pdf)|"
    r"the\s+selected\s+(?:report|document|pdf)"
    r")\b"
)

_CROSS_DOC_RE = re.compile(
    r"(?i)\b("
    r"compare|comparison|versus|vs\.?|across\s+(?:the\s+)?(?:two|both|these)|"
    r"between\s+(?:the\s+)?(?:two|both|these)|"
    r"common\s+between|both\s+reports?|these\s+two\s+reports?|"
    r"across\s+(?:the\s+)?(?:geological\s+)?(?:reports?|documents?)|"
    r"which\s+report\s+(?:has|shows|reports?)|"
    r"how\s+does\b.+\bcompare\b"
    r")\b"
)


def is_deictic_document_query(question: str) -> bool:
    """True when the user refers to 'this report/document' rather than naming it."""
    q = question or ""
    if _DEICTIC_RE.search(q):
        return True
    # Bare geological listing with no named place often means current document
    if re.search(
        r"(?i)\b(?:what|which|list)\b.+\b(?:seams?|boreholes?|lithology|formations?)\b",
        q,
    ) and not re.search(
        r"(?i)\b(?:in|of|for|from|about)\s+[A-Z][A-Za-z0-9][A-Za-z0-9 ._-]{2,}",
        q,
    ):
        # Only treat as deictic if no explicit place/document tokens of length >= 4
        # beyond stopwords — keep conservative: require explicit this/current OR
        # very short generic phrasing without a place name.
        if re.search(
            r"(?i)\b(?:reported|mentioned|identified|present)\b.+\b(?:report|document)?\b",
            q,
        ) and not _tokens_look_like_place(q):
            return True
    return False


def _tokens_look_like_place(question: str) -> bool:
    """Heuristic: capitalized multi-word / long tokens suggest a named place/doc."""
    # Strip deictic / question words then look for remaining content nouns
    cleaned = re.sub(
        r"(?i)\b(?:what|which|are|is|the|a|an|in|of|for|from|about|reported|"
        r"mentioned|identified|present|coal|seams?|seam|boreholes?|borehole|"
        r"lithology|formations?|exploration|report|document|pdf|thickness|"
        r"depths?|their|this)\b",
        " ",
        question or "",
    )
    toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", cleaned) if t.lower() not in {"block"}]
    return len(toks) >= 1


def is_cross_document_query(question: str) -> bool:
    return bool(_CROSS_DOC_RE.search(question or ""))


def resolve_documents_for_entity(
    db: Session,
    entity: Optional[str],
    *,
    limit: int = 5,
) -> list[ResolvedDocument]:
    """Match an entity/document phrase against indexed document filenames/titles."""
    if not entity or not entity.strip():
        return []
    want = _tokens(entity)
    if not want:
        return []

    docs = (
        db.query(Document)
        .filter(Document.index_status == IndexStatus.INDEXED.value)
        .all()
    )
    if not docs:
        docs = db.query(Document).all()

    scored: list[ResolvedDocument] = []
    for d in docs:
        blob = " ".join(
            filter(
                None,
                [
                    d.original_filename,
                    d.filename,
                    d.mine_name,
                    (d.meta or {}).get("title") if isinstance(d.meta, dict) else None,
                ],
            )
        )
        have = set(_tokens(blob))
        if not have:
            continue
        inter = set(want) & have
        if not inter:
            continue
        recall = len(inter) / max(len(want), 1)
        precision = len(inter) / max(len(have), 1)
        score = recall * 0.75 + precision * 0.25
        longest = max(want, key=len)
        if longest in have:
            score += 0.15
        if score < 0.35:
            continue
        scored.append(
            ResolvedDocument(
                document_id=d.id,
                original_filename=d.original_filename or d.filename,
                match_score=score,
            )
        )
    scored.sort(key=lambda x: x.match_score, reverse=True)
    return scored[:limit]


def primary_document_id(db: Session, entity: Optional[str]) -> Optional[str]:
    hits = resolve_documents_for_entity(db, entity, limit=1)
    return hits[0].document_id if hits else None


def document_family_ids(db: Session, document_id: str) -> list[str]:
    """All document IDs that are duplicates/versions of the same report filename."""
    doc = db.get(Document, document_id)
    if not doc:
        return [document_id] if document_id else []
    key = filename_key(doc.original_filename or doc.filename)
    if not key:
        return [document_id]
    family: list[Document] = []
    for d in db.query(Document).all():
        if filename_key(d.original_filename or d.filename) == key:
            family.append(d)
        elif d.parent_document_id and (
            d.parent_document_id == document_id
            or d.id == getattr(doc, "parent_document_id", None)
        ):
            family.append(d)
    if not family:
        return [document_id]
    # Prefer newest / highest version first, but return all IDs for retrieval union
    family.sort(
        key=lambda d: (
            d.version or 1,
            d.created_at.timestamp() if d.created_at else 0,
        ),
        reverse=True,
    )
    return [d.id for d in family]


def prefer_canonical_ids(db: Session, document_ids: list[str]) -> list[str]:
    """Collapse duplicate uploads of the same filename to the newest row per family.

    Retrieval may still include the full family via document_family_ids when scoping
    a single current document; this helper is for multi-match entity resolution.
    """
    if not document_ids:
        return []
    docs = {d.id: d for d in db.query(Document).filter(Document.id.in_(document_ids)).all()}
    best: dict[str, Document] = {}
    for did in document_ids:
        d = docs.get(did)
        if not d:
            continue
        key = filename_key(d.original_filename or d.filename) or did
        cur = best.get(key)
        if cur is None:
            best[key] = d
            continue
        cur_key = (cur.version or 1, cur.created_at.timestamp() if cur.created_at else 0)
        new_key = (d.version or 1, d.created_at.timestamp() if d.created_at else 0)
        if new_key >= cur_key:
            best[key] = d
    return [d.id for d in best.values()]


def resolve_document_scope(
    db: Session,
    *,
    question: str,
    entity: Optional[str],
    entities: Optional[list[str]] = None,
    current_document_id: Optional[str] = None,
    session_document_id: Optional[str] = None,
    is_geological: bool = False,
) -> DocumentScope:
    """Decide which document IDs may contribute evidence for this query."""
    q = question or ""
    cross = is_cross_document_query(q)
    deictic = is_deictic_document_query(q)
    active_id = (current_document_id or session_document_id or "").strip() or None

    if cross:
        # Explicit comparison: resolve each named entity / allow multiple
        allowed: list[str] = []
        names: list[str] = []
        for ent in entities or ([entity] if entity else []):
            for r in resolve_documents_for_entity(db, ent, limit=3):
                if r.document_id not in allowed:
                    allowed.append(r.document_id)
                    names.append(r.original_filename)
        # Expand each to family then collapse to canonical per family for listing,
        # but keep all family IDs so both duplicate copies' chunks are readable
        expanded: list[str] = []
        for did in prefer_canonical_ids(db, allowed) or allowed:
            for fid in document_family_ids(db, did):
                if fid not in expanded:
                    expanded.append(fid)
        return DocumentScope(
            mode="cross_document_comparison",
            allowed_ids=expanded,
            primary_id=expanded[0] if expanded else None,
            primary_name=names[0] if names else None,
            reason="cross_document_comparison",
        )

    # "This report / this document" WITHOUT a selected document must NOT
    # fall through to unrestricted multi-document RAG.
    if deictic and not active_id and is_geological:
        return DocumentScope(
            mode="single_document",
            allowed_ids=[],
            primary_id=None,
            primary_name=None,
            reason="deictic_missing_current_document",
        )

    # Current/selected document: exact ID only (not the whole duplicate family).
    # Family IDs are used only for duplicate page-content dedupe/display, not
    # to widen retrieval across other reports.
    if active_id and is_geological and not cross:
        family_set = set(document_family_ids(db, active_id))
        # Explicit other-document entity (resolves outside the current family)
        # only when the user named a place/document — never for bare metric asks.
        named_place = bool(entity) and _tokens_look_like_place(q) and not deictic
        if named_place and entity:
            resolved = resolve_documents_for_entity(db, entity, limit=5)
            other = [r for r in resolved if r.document_id not in family_set]
            if other and not any(r.document_id in family_set for r in resolved):
                canon = prefer_canonical_ids(db, [r.document_id for r in other])
                expanded: list[str] = []
                for did in canon:
                    for fid in document_family_ids(db, did):
                        if fid not in expanded:
                            expanded.append(fid)
                primary = db.get(Document, canon[0]) if canon else None
                return DocumentScope(
                    mode="single_document" if len(canon) == 1 else "multi_document",
                    allowed_ids=expanded,
                    primary_id=canon[0] if canon else None,
                    primary_name=(
                        (primary.original_filename or primary.filename)
                        if primary
                        else other[0].original_filename
                    ),
                    reason="entity_other_document",
                )
        doc = db.get(Document, active_id)
        return DocumentScope(
            mode="single_document",
            # Exact selected document only — duplicates of the same PDF are
            # collapsed later via filename+page dedupe, not by widening scope.
            allowed_ids=[active_id],
            primary_id=active_id,
            primary_name=(doc.original_filename or doc.filename) if doc else None,
            reason=(
                "current_document_deictic"
                if deictic
                else "current_document_geological_default"
            ),
        )

    # Named entity → resolve documents (no current document selected)
    if entity:
        resolved = resolve_documents_for_entity(db, entity, limit=8)
        if resolved:
            canon = prefer_canonical_ids(db, [r.document_id for r in resolved])
            expanded: list[str] = []
            for did in canon:
                for fid in document_family_ids(db, did):
                    if fid not in expanded:
                        expanded.append(fid)
            primary = db.get(Document, canon[0]) if canon else None
            mode = "single_document" if len(canon) == 1 else "multi_document"
            return DocumentScope(
                mode=mode,
                allowed_ids=expanded,
                primary_id=canon[0] if canon else None,
                primary_name=(
                    (primary.original_filename or primary.filename) if primary else resolved[0].original_filename
                ),
                reason="entity_resolved",
            )

    return DocumentScope(mode="multi_document", allowed_ids=[], reason="unscoped")


def filter_hits_by_scope(hits: list, allowed_ids: list[str]) -> tuple[list, list[str]]:
    """Keep only hits whose document_id is in allowed_ids. Returns (kept, rejected_doc_names)."""
    if not allowed_ids:
        return hits, []
    allow = set(allowed_ids)
    kept = []
    rejected: list[str] = []
    for h in hits:
        did = getattr(h, "document_id", None)
        if did in allow:
            kept.append(h)
        else:
            name = getattr(h, "document_name", None) or did or "?"
            if name not in rejected:
                rejected.append(str(name))
    return kept, rejected


def dedupe_evidence_by_page_content(hits: list) -> list:
    """Drop duplicate evidence from re-uploaded copies of the same report page."""
    seen: set[str] = set()
    out = []
    for h in hits:
        name = filename_key(getattr(h, "document_name", None))
        page = getattr(h, "page", None)
        text = (getattr(h, "evidence_text", None) or getattr(h, "text", None) or "")[:160]
        text_key = _norm(text)[:80]
        key = f"{name}|{page}|{text_key}|{getattr(h, 'value', '')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def log_scope_forensics(
    *,
    query: str,
    scope: DocumentScope,
    structured_docs: list[str],
    rag_docs: list[str],
    rejected: list[str],
    final_docs: list[str],
    final_pages: list,
    qwen_called: bool,
    qwen_model: Optional[str],
    requested_domain: Optional[str] = None,
    requested_metric: Optional[str] = None,
    rejection_reasons: Optional[list[str]] = None,
    final_metrics: Optional[list[str]] = None,
    allowed_document_ids: Optional[list[str]] = None,
) -> None:
    logger.info(
        "DOC_SCOPE QUERY=%r CURRENT_DOCUMENT=%r CURRENT_DOCUMENT_ID=%r "
        "ALLOWED_DOCUMENT_IDS=%s REQUESTED_DOMAIN=%s REQUESTED_METRIC=%s "
        "DOCUMENT_SCOPE=%s RAW_STRUCTURED_DOCUMENTS=%s RAW_RAG_DOCUMENTS=%s "
        "REJECTED_DOCUMENTS=%s REJECTION_REASONS=%s "
        "FINAL_EVIDENCE_DOCUMENTS=%s FINAL_EVIDENCE_PAGES=%s FINAL_EVIDENCE_METRICS=%s "
        "QWEN_CALLED=%s QWEN_MODEL=%s REASON=%s",
        (query or "")[:200],
        scope.primary_name,
        scope.primary_id,
        allowed_document_ids if allowed_document_ids is not None else scope.allowed_ids,
        requested_domain,
        requested_metric,
        scope.mode,
        structured_docs,
        rag_docs,
        rejected,
        rejection_reasons or [],
        final_docs,
        final_pages,
        final_metrics or [],
        qwen_called,
        qwen_model,
        scope.reason,
    )
