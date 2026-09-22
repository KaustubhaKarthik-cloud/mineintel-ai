"""Safe structured fact retrieval (no arbitrary SQL from the LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ConflictStatus, Document, ExtractedFact, FactStatus, ValidationConflict
from app.validation.rules import normalize_entity, normalize_field, normalize_period
from app.validation.service import list_conflicts

VERIFIED_STATUSES = {
    FactStatus.HIGH_CONFIDENCE.value,
    FactStatus.APPROVED.value,
    FactStatus.CORRECTED.value,
}


@dataclass
class StructuredFactHit:
    entity: str
    metric: str
    period: Optional[str]
    value: Optional[str]
    numeric_value: Optional[float]
    unit: Optional[str]
    status: str
    document_id: str
    document_name: str
    document_version: int
    page: Optional[int]
    sheet_name: Optional[str]
    evidence_text: Optional[str]
    fact_id: str
    confidence: float
    # Optional geological context (ignored by mining paths)
    seam_name: Optional[str] = None
    borehole_id: Optional[str] = None
    geological_formation: Optional[str] = None
    seam_status: Optional[str] = None
    value_min: Optional[str] = None
    value_max: Optional[str] = None
    value_min_normalized: Optional[float] = None
    value_max_normalized: Optional[float] = None
    measurement_type: Optional[str] = None


# Controlled org aliases only — never character-substring (CIL ↛ NLCIL).
_CONTROLLED_ENTITY_ALIASES: dict[str, frozenset[str]] = {
    "nlcil": frozenset({"nlcil", "nlc india limited", "nlc india", "nlc"}),
    "nlc india limited": frozenset({"nlcil", "nlc india limited", "nlc india", "nlc"}),
    "nlc india": frozenset({"nlcil", "nlc india limited", "nlc india", "nlc"}),
    "cil": frozenset({"cil", "coal india", "coal india limited", "coal india ltd"}),
    "coal india limited": frozenset({"cil", "coal india", "coal india limited", "coal india ltd"}),
    "coal india": frozenset({"cil", "coal india", "coal india limited", "coal india ltd"}),
}


def _entity_alias_set(normalized: str) -> frozenset[str]:
    return _CONTROLLED_ENTITY_ALIASES.get(normalized, frozenset({normalized}))


def _entity_soft_match(want: Optional[str], have: Optional[str]) -> bool:
    """Controlled entity match — never broad substring (CIL must not match NLCIL)."""
    if not want:
        return True
    if not have:
        return False
    wn = normalize_entity(want) or ""
    hn = normalize_entity(have) or ""
    if not wn or not hn:
        return False
    if wn == hn:
        return True
    # Controlled aliases (NLCIL ↔ NLC India Limited; CIL ↔ Coal India — disjoint)
    if _entity_alias_set(wn) & _entity_alias_set(hn):
        return True
    wa = set(wn.split())
    ha_set = set(hn.split())
    if not wa or not ha_set:
        return False
    if wa == ha_set:
        return True
    if wa <= ha_set or ha_set <= wa:
        shorter, longer = (wa, ha_set) if len(wa) <= len(ha_set) else (ha_set, wa)
        if len(shorter) == 1 and len(longer) == 1:
            a, b = next(iter(shorter)), next(iter(longer))
            if a != b and (a in b or b in a):
                return False
        return True
    inter = wa & ha_set
    if len(inter) >= min(2, len(wa)) and (len(inter) / max(len(wa), 1)) >= 0.5:
        return True
    # Single-token: exact token membership only (no "cil" inside "nlcil")
    if len(wa) == 1:
        token = next(iter(wa))
        return token in ha_set
    return False


def retrieve_structured_facts(
    db: Session,
    *,
    entity: Optional[str] = None,
    metric: Optional[str] = None,
    periods: Optional[list[str]] = None,
    verified_only: bool = True,
) -> list[StructuredFactHit]:
    q = db.query(ExtractedFact).filter(ExtractedFact.status != FactStatus.REJECTED.value)
    if verified_only:
        q = q.filter(ExtractedFact.status.in_(VERIFIED_STATUSES))
    q = q.filter(ExtractedFact.is_calculated.is_(False))
    facts = q.all()

    docs = {d.id: d for d in db.query(Document).all()}
    latest: dict[str, Document] = {}
    for d in docs.values():
        key = (d.original_filename or d.filename).lower()
        prev = latest.get(key)
        if prev is None or (d.version or 1) >= (prev.version or 1):
            latest[key] = d
    latest_ids = {d.id for d in latest.values()}

    want_metric = normalize_field(metric) if metric else None
    want_periods = {normalize_period(p) for p in (periods or []) if normalize_period(p)}

    hits: list[StructuredFactHit] = []
    for f in facts:
        if f.document_id not in latest_ids:
            continue
        f_metric = normalize_field(f.field_name)
        f_entity = f.entity_name
        f_period = normalize_period(f.financial_year)
        if want_metric and f_metric != want_metric:
            continue
        if entity and not _entity_soft_match(entity, f_entity):
            continue
        if want_periods and f_period not in want_periods:
            continue
        doc = docs.get(f.document_id)
        hits.append(
            StructuredFactHit(
                entity=f.entity_name or entity or "Unknown",
                metric=f_metric or f.field_name,
                period=f_period or f.financial_year,
                value=f.value,
                numeric_value=f.numeric_value,
                unit=f.unit,
                status=f.status,
                document_id=f.document_id,
                document_name=(doc.original_filename if doc else f.document_id),
                document_version=(doc.version if doc else 1) or 1,
                page=f.page_number,
                sheet_name=f.sheet_name,
                evidence_text=f.evidence_text,
                fact_id=f.id,
                confidence=f.confidence_score or 0.0,
            )
        )
    return hits


def conflicts_for_structured(
    db: Session,
    *,
    entity: Optional[str],
    metric: Optional[str],
    periods: Optional[list[str]] = None,
) -> list[ValidationConflict]:
    rows = list_conflicts(db)
    want_entity = normalize_entity(entity) if entity else None
    want_metric = normalize_field(metric) if metric else None
    want_periods = {normalize_period(p) for p in (periods or []) if normalize_period(p)}
    out: list[ValidationConflict] = []
    for c in rows:
        if c.status in {ConflictStatus.DISMISSED.value, ConflictStatus.RESOLVED.value}:
            continue
        if want_metric and normalize_field(c.field_name) != want_metric:
            continue
        if want_entity:
            ce = normalize_entity(c.entity_name) or ""
            # Exact normalized match only — never "cil" contained in "nlcil"
            if ce != want_entity:
                continue
        if want_periods:
            cp = normalize_period(c.period)
            if cp and cp not in want_periods:
                continue
        out.append(c)
    return out
