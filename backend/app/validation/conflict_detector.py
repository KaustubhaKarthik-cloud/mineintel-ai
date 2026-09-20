"""Conflict detection over grouped Phase 3 facts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

from app.models import ExtractedFact
from app.validation.comparator import compare_numeric
from app.validation.rules import (
    entities_match,
    normalize_entity,
    normalize_field,
    normalize_period,
)
from app.validation.validators import check_achievement_discrepancy


@dataclass
class EvidenceDraft:
    fact: ExtractedFact
    document_name: str
    document_version: int
    label: str
    value: Optional[str]
    unit: Optional[str]
    numeric_value: Optional[float]
    normalized_value: Optional[float]
    is_calculated: bool = False


@dataclass
class ConflictDraft:
    fingerprint: str
    conflict_type: str
    entity_name: Optional[str]
    field_name: str
    period: Optional[str]
    severity: str
    description: str
    evidence: list[EvidenceDraft] = field(default_factory=list)


def _fingerprint(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _display_entity(fact: ExtractedFact) -> str:
    return fact.entity_name or "Unknown entity"


def detect_cross_document_conflicts(
    facts: list[ExtractedFact],
    doc_meta: dict[str, tuple[str, int]],
) -> list[ConflictDraft]:
    """Group by entity+field+period and compare across documents."""
    # Exclude rejected; keep calculated out of cross-doc numeric groups except as labeled
    usable = [f for f in facts if f.status != "rejected" and f.numeric_value is not None]
    groups: dict[tuple[str, str, str], list[ExtractedFact]] = {}
    ambiguous_pairs: list[ConflictDraft] = []

    # Pre-check ambiguous entity pairs that share field+period
    for a, b in combinations(usable, 2):
        if a.document_id == b.document_id:
            continue
        fa, fb = normalize_field(a.field_name), normalize_field(b.field_name)
        if not fa or fa != fb:
            continue
        pa, pb = normalize_period(a.financial_year), normalize_period(b.financial_year)
        if pa != pb:
            continue
        match = entities_match(a.entity_name, b.entity_name)
        if match == "ambiguous":
            fp = _fingerprint("entity", fa, pa or "", normalize_entity(a.entity_name) or "", normalize_entity(b.entity_name) or "")
            ambiguous_pairs.append(
                ConflictDraft(
                    fingerprint=fp,
                    conflict_type="entity_match_review",
                    entity_name=f"{a.entity_name} / {b.entity_name}",
                    field_name=fa,
                    period=pa,
                    severity="medium",
                    description=(
                        f"Ambiguous entity match for {fa} ({pa or 'unknown period'}): "
                        f"'{a.entity_name}' vs '{b.entity_name}'. Human review required before merging."
                    ),
                    evidence=[
                        _evidence_from_fact(a, doc_meta, "A"),
                        _evidence_from_fact(b, doc_meta, "B"),
                    ],
                )
            )

    for fact in usable:
        if fact.is_calculated:
            continue
        field = normalize_field(fact.field_name)
        entity = normalize_entity(fact.entity_name)
        period = normalize_period(fact.financial_year)
        if not field or not entity or not period:
            continue
        groups.setdefault((entity, field, period), []).append(fact)

    conflicts: list[ConflictDraft] = []
    seen_fp: set[str] = set()

    for (entity, field, period), members in groups.items():
        # Deduplicate by document — keep latest version per original filename key
        by_doc: dict[str, ExtractedFact] = {}
        for f in members:
            name, ver = doc_meta.get(f.document_id, (f.document_id, 1))
            key = name.lower()
            prev = by_doc.get(key)
            if prev is None:
                by_doc[key] = f
            else:
                _, pver = doc_meta.get(prev.document_id, ("", 1))
                if ver >= pver:
                    by_doc[key] = f

        reps = list(by_doc.values())
        if len(reps) < 2:
            continue

        for a, b in combinations(reps, 2):
            if a.document_id == b.document_id:
                continue
            cmp = compare_numeric(a.numeric_value, a.unit, b.numeric_value, b.unit)
            if cmp.unit_review or cmp.incompatible_units:
                fp = _fingerprint("unit", entity, field, period, a.id, b.id)
                if fp in seen_fp:
                    continue
                seen_fp.add(fp)
                conflicts.append(
                    ConflictDraft(
                        fingerprint=fp,
                        conflict_type="unit_review",
                        entity_name=_display_entity(a),
                        field_name=field,
                        period=period,
                        severity="low",
                        description=(
                            f"Unit review required for {field} ({period}) on {_display_entity(a)}: "
                            f"{a.value} {a.unit or ''} vs {b.value} {b.unit or ''}."
                        ),
                        evidence=[
                            _evidence_from_fact(a, doc_meta, "A", cmp.left_base),
                            _evidence_from_fact(b, doc_meta, "B", cmp.right_base),
                        ],
                    )
                )
                continue

            if not cmp.conflict:
                continue

            fp = _fingerprint("contra", entity, field, period, a.document_id, b.document_id)
            # stable order
            ids = sorted([a.document_id, b.document_id])
            fp = _fingerprint("contra", entity, field, period, ids[0], ids[1])
            if fp in seen_fp:
                continue
            seen_fp.add(fp)
            conflicts.append(
                ConflictDraft(
                    fingerprint=fp,
                    conflict_type="contradiction",
                    entity_name=_display_entity(a),
                    field_name=field,
                    period=period,
                    severity="high",
                    description=(
                        f"Potential conflict: {_display_entity(a)} {field} {period} — "
                        f"{a.value} {a.unit or ''} vs {b.value} {b.unit or ''}. "
                        "Human verification required."
                    ),
                    evidence=[
                        _evidence_from_fact(a, doc_meta, "A", cmp.left_base),
                        _evidence_from_fact(b, doc_meta, "B", cmp.right_base),
                    ],
                )
            )

    # Dedup ambiguous
    for draft in ambiguous_pairs:
        if draft.fingerprint not in seen_fp:
            seen_fp.add(draft.fingerprint)
            conflicts.append(draft)

    return conflicts


def detect_reported_calculated_discrepancies(
    facts: list[ExtractedFact],
    doc_meta: dict[str, tuple[str, int]],
) -> list[ConflictDraft]:
    """Within a document: reported achievement vs production/target calculation."""
    by_doc: dict[str, list[ExtractedFact]] = {}
    for f in facts:
        if f.status == "rejected":
            continue
        by_doc.setdefault(f.document_id, []).append(f)

    out: list[ConflictDraft] = []
    for doc_id, members in by_doc.items():
        # group by entity+period
        buckets: dict[tuple[str, str], dict[str, ExtractedFact]] = {}
        for f in members:
            if f.is_calculated:
                continue
            entity = normalize_entity(f.entity_name) or ""
            period = normalize_period(f.financial_year) or ""
            field = normalize_field(f.field_name) or ""
            if not entity or not period or not field:
                continue
            buckets.setdefault((entity, period), {})[field] = f

        for (entity, period), fields in buckets.items():
            prod = fields.get("production")
            target = fields.get("production_target")
            ach = fields.get("achievement_percentage")
            if not prod or not target or not ach:
                continue
            result = check_achievement_discrepancy(
                prod.numeric_value, target.numeric_value, ach.numeric_value
            )
            if not result.detected:
                continue
            fp = _fingerprint("disc", doc_id, entity, period)
            # synthetic calculated evidence (not stored as overwriting fact)
            calc_ev = EvidenceDraft(
                fact=ach,
                document_name=doc_meta.get(doc_id, (doc_id, 1))[0],
                document_version=doc_meta.get(doc_id, (doc_id, 1))[1],
                label="calculated",
                value=str(result.calculated),
                unit="%",
                numeric_value=result.calculated,
                normalized_value=result.calculated,
                is_calculated=True,
            )
            out.append(
                ConflictDraft(
                    fingerprint=fp,
                    conflict_type="discrepancy",
                    entity_name=prod.entity_name,
                    field_name="achievement_percentage",
                    period=period,
                    severity="medium",
                    description=result.message,
                    evidence=[
                        _evidence_from_fact(ach, doc_meta, "reported"),
                        calc_ev,
                        _evidence_from_fact(prod, doc_meta, "production"),
                        _evidence_from_fact(target, doc_meta, "target"),
                    ],
                )
            )
    return out


def _evidence_from_fact(
    fact: ExtractedFact,
    doc_meta: dict[str, tuple[str, int]],
    label: str,
    normalized: Optional[float] = None,
) -> EvidenceDraft:
    name, ver = doc_meta.get(fact.document_id, (fact.document_id, 1))
    return EvidenceDraft(
        fact=fact,
        document_name=name,
        document_version=ver,
        label=label,
        value=fact.value,
        unit=fact.unit,
        numeric_value=fact.numeric_value,
        normalized_value=normalized if normalized is not None else fact.numeric_value,
        is_calculated=bool(fact.is_calculated),
    )
