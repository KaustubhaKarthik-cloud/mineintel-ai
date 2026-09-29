"""G3 geological validation + conflict / discrepancy detection.

Generic only: no document names, pages, or hard-coded values.
Conflicts require same logical context (entity + metric_kind + units).
Cross-document disagreements are discrepancies, not automatic contradictions.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from app.geology.entities import boreholes_match, formations_match, seams_match
from app.geology.metric_kinds import (
    FORMATION_THICKNESS,
    MINIMUM_WORKABLE_SEAM_THICKNESS,
    SEAM_PARTING_THICKNESS,
    metrics_compatible,
)
from app.geology.units import to_metres
from app.validation.comparator import compare_numeric, values_within_tolerance


CONFLICT_METRICS = frozenset(
    {
        "seam_thickness",
        "seam_depth",
        "borehole_depth",
        "formation_thickness",
        "seam_parting_thickness",
        "overburden_thickness",
        "minimum_workable_seam_thickness",
        "coal_quality",
        "resource",
        "reserve",
        "resource_quantity",
        "reserve_quantity",
    }
)

# Metrics that must never be treated as interchangeable
INCOMPATIBLE_METRIC_PAIRS = frozenset(
    {
        frozenset({"seam_thickness", "formation_thickness"}),
        frozenset({"seam_thickness", "minimum_workable_seam_thickness"}),
        frozenset({"seam_thickness", "seam_parting_thickness"}),
        frozenset({"seam_thickness", "overburden_thickness"}),
        frozenset({"seam_depth", "borehole_depth"}),
        frozenset({"formation_thickness", "minimum_workable_seam_thickness"}),
    }
)


@dataclass
class GeologicalValidationIssue:
    code: str
    message: str
    severity: str = "medium"  # low | medium | high
    fact_id: Optional[str] = None


@dataclass
class GeologicalConflictDraft:
    """Structured conflict / discrepancy for assistant + review."""

    id: str
    conflict_type: str  # geological_value_mismatch | cross_document_discrepancy
    entity_name: Optional[str]
    field_name: str  # metric_kind
    period: Optional[str] = None
    status: str = "review_required"
    severity: str = "medium"
    description: str = ""
    requires_human_review: bool = True
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conflict_type": self.conflict_type,
            "entity_name": self.entity_name,
            "field_name": self.field_name,
            "period": self.period,
            "status": self.status,
            "severity": self.severity,
            "description": self.description,
            "requires_human_review": self.requires_human_review,
            "evidence": list(self.evidence),
        }


def _parse_numeric(value: Optional[str], numeric: Optional[float] = None) -> Optional[float]:
    if numeric is not None:
        try:
            return float(numeric)
        except (TypeError, ValueError):
            pass
    if not value:
        return None
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(value).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _range_bounds(hit) -> Optional[tuple[float, float]]:
    """Return (lo, hi) in metres when possible; else None."""
    lo_n = getattr(hit, "value_min_normalized", None)
    hi_n = getattr(hit, "value_max_normalized", None)
    if lo_n is not None and hi_n is not None:
        return float(lo_n), float(hi_n)

    unit = getattr(hit, "unit", None) or "m"
    vmin = getattr(hit, "value_min", None)
    vmax = getattr(hit, "value_max", None)
    if vmin is not None and vmax is not None:
        a = _parse_numeric(str(vmin))
        b = _parse_numeric(str(vmax))
        if a is not None and b is not None:
            am = to_metres(a, unit)
            bm = to_metres(b, unit)
            if am is not None and bm is not None:
                return min(am, bm), max(am, bm)

    v = _parse_numeric(getattr(hit, "value", None), getattr(hit, "numeric_value", None))
    if v is None:
        return None
    vm = to_metres(v, unit)
    if vm is None:
        return None
    return vm, vm


def _overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return not (a[1] < b[0] - 1e-6 or b[1] < a[0] - 1e-6)


def _point_in_range(point: float, rng: tuple[float, float]) -> bool:
    return rng[0] - 1e-6 <= point <= rng[1] + 1e-6


def _entity_key(hit) -> str:
    """Stable logical entity key for conflict grouping."""
    seam = getattr(hit, "seam_name", None)
    status = (getattr(hit, "seam_status", None) or "").lower()
    formation = getattr(hit, "geological_formation", None) or ""
    bh = getattr(hit, "borehole_id", None) or ""
    if seam:
        from app.geology.entities import seam_match_key

        return f"seam:{seam_match_key(seam)}"
    if status in {"uncorrelated", "unnamed"}:
        from app.geology.entities import formation_match_key

        return f"unnamed:{status}:{formation_match_key(formation)}"
    if bh:
        from app.geology.entities import borehole_match_key

        return f"bh:{borehole_match_key(bh)}"
    if formation:
        from app.geology.entities import formation_match_key

        return f"fm:{formation_match_key(formation)}"
    ent = (getattr(hit, "entity", None) or "").strip().lower()
    return f"ent:{re.sub(r'[^a-z0-9]+', '', ent)}" if ent else "ent:unknown"


def _same_entity(a, b) -> bool:
    """True when two hits refer to the same geological entity."""
    if seams_match(getattr(a, "seam_name", None), getattr(b, "seam_name", None)):
        # Same named seam — borehole must match when both present
        ba, bb = getattr(a, "borehole_id", None), getattr(b, "borehole_id", None)
        if ba and bb and not boreholes_match(ba, bb):
            return False
        return True
    sa = (getattr(a, "seam_status", None) or "").lower()
    sb = (getattr(b, "seam_status", None) or "").lower()
    if sa in {"uncorrelated", "unnamed"} and sb in {"uncorrelated", "unnamed"}:
        return formations_match(
            getattr(a, "geological_formation", None),
            getattr(b, "geological_formation", None),
        )
    if getattr(a, "borehole_id", None) and getattr(b, "borehole_id", None):
        if boreholes_match(a.borehole_id, b.borehole_id):
            # Same borehole — for lithology/quality OK; for seam metrics need seam match
            metric = (getattr(a, "metric", None) or "").lower()
            if metric.startswith("seam_") or metric in {"seam_thickness", "seam_depth"}:
                return seams_match(getattr(a, "seam_name", None), getattr(b, "seam_name", None))
            return True
    return False


def validate_geological_hit(hit) -> list[GeologicalValidationIssue]:
    """Lightweight validation of a structured geological hit."""
    issues: list[GeologicalValidationIssue] = []
    metric = (getattr(hit, "metric", None) or "").lower()
    value = getattr(hit, "value", None)
    unit = getattr(hit, "unit", None)

    if metric in CONFLICT_METRICS and value:
        if re.search(r"[<>~≈]|approximately|about\s+\d", str(value), re.I):
            # Qualifiers are allowed — do not treat as malformed
            pass
        elif not re.search(r"\d", str(value)):
            issues.append(
                GeologicalValidationIssue(
                    code="non_numeric_measure",
                    message="Measure metric lacks a numeric value.",
                    fact_id=getattr(hit, "fact_id", None),
                )
            )

    # Metric / entity consistency
    if metric == "seam_thickness":
        if not getattr(hit, "seam_name", None):
            issues.append(
                GeologicalValidationIssue(
                    code="seam_thickness_missing_seam",
                    message="Seam thickness without a named seam association.",
                    severity="high",
                    fact_id=getattr(hit, "fact_id", None),
                )
            )
        ev = (getattr(hit, "evidence_text", None) or "").lower()
        if re.search(r"(?i)\b(?:minimum\s+)?workable\s+thickness\b", ev):
            issues.append(
                GeologicalValidationIssue(
                    code="workable_mislabelled_as_seam_thickness",
                    message="Workable thickness must not be labelled seam_thickness.",
                    severity="high",
                    fact_id=getattr(hit, "fact_id", None),
                )
            )

    if metric == FORMATION_THICKNESS and getattr(hit, "seam_name", None):
        issues.append(
            GeologicalValidationIssue(
                code="formation_thickness_has_seam",
                message="Formation thickness should not carry a seam identifier.",
                severity="medium",
                fact_id=getattr(hit, "fact_id", None),
            )
        )

    if unit and metric in CONFLICT_METRICS:
        from app.geology.units import canonicalize_length_unit as _canon

        lengthish = metric in {
            "seam_thickness",
            "formation_thickness",
            "seam_parting_thickness",
            "overburden_thickness",
            "minimum_workable_seam_thickness",
            "seam_depth",
            "borehole_depth",
        }
        if lengthish and unit and _canon(unit) is None and unit.lower() not in {"%", "kcal/kg"}:
            issues.append(
                GeologicalValidationIssue(
                    code="unrecognized_unit",
                    message=f"Unit {unit!r} may need review.",
                    severity="low",
                    fact_id=getattr(hit, "fact_id", None),
                )
            )

    return issues


def metrics_are_comparable(m1: Optional[str], m2: Optional[str]) -> bool:
    a = (m1 or "").lower()
    b = (m2 or "").lower()
    if not a or not b:
        return False
    if a == b:
        return True
    if frozenset({a, b}) in INCOMPATIBLE_METRIC_PAIRS:
        return False
    return metrics_compatible(a, b) and metrics_compatible(b, a)


def _values_disagree(a, b) -> bool:
    ra, rb = _range_bounds(a), _range_bounds(b)
    if ra is None or rb is None:
        # Fall back to raw numeric compare with units
        va = _parse_numeric(getattr(a, "value", None), getattr(a, "numeric_value", None))
        vb = _parse_numeric(getattr(b, "value", None), getattr(b, "numeric_value", None))
        if va is None or vb is None:
            return False
        cmp = compare_numeric(va, getattr(a, "unit", None), vb, getattr(b, "unit", None))
        if cmp.incompatible_units or cmp.unit_review:
            return False
        return bool(cmp.conflict)
    # Compatible if ranges overlap or point-in-range
    if _overlaps(ra, rb):
        return False
    if ra[0] == ra[1] and rb[0] != rb[1] and _point_in_range(ra[0], rb):
        return False
    if rb[0] == rb[1] and ra[0] != ra[1] and _point_in_range(rb[0], ra):
        return False
    # Normalized metre compare with tolerance for point values
    if ra[0] == ra[1] and rb[0] == rb[1]:
        return not values_within_tolerance(ra[0], rb[0])
    return True


def detect_geological_conflicts(
    hits: list,
    *,
    allow_cross_document: bool = True,
) -> list[GeologicalConflictDraft]:
    """Detect same-context conflicts and cross-document discrepancies.

    Same document + same entity + same metric + compatible units + disagreeing values
    → geological_value_mismatch (requires human review).

    Different documents + same entity + same metric + disagreeing values
    → cross_document_discrepancy (show both; do not auto-contradict).
    """
    usable = [
        h
        for h in hits
        if (getattr(h, "metric", None) or "").lower() in CONFLICT_METRICS
        and (getattr(h, "value", None) or getattr(h, "value_min", None))
        and getattr(h, "status", None) != "rejected"
    ]
    if len(usable) < 2:
        return []

    # Group by entity key + metric (+ borehole when seam metric)
    groups: dict[tuple, list] = defaultdict(list)
    for h in usable:
        metric = (h.metric or "").lower()
        ek = _entity_key(h)
        bh = ""
        if getattr(h, "borehole_id", None):
            from app.geology.entities import borehole_match_key

            bh = borehole_match_key(h.borehole_id)
        groups[(ek, metric, bh)].append(h)

    drafts: list[GeologicalConflictDraft] = []
    for (ek, metric, bh), members in groups.items():
        if len(members) < 2:
            continue
        # Pairwise within group
        seen_pairs: set[tuple[str, str]] = set()
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if not metrics_are_comparable(a.metric, b.metric):
                    continue
                if not _same_entity(a, b):
                    continue
                # Different boreholes for seam thickness → separate observations
                ba, bb = getattr(a, "borehole_id", None), getattr(b, "borehole_id", None)
                if ba and bb and not boreholes_match(ba, bb):
                    continue
                if not _values_disagree(a, b):
                    continue
                fa, fb = sorted([a.fact_id or id(a), b.fact_id or id(b)])
                pair_key = (str(fa), str(fb))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                same_doc = a.document_id == b.document_id
                if not same_doc and not allow_cross_document:
                    continue
                ctype = (
                    "geological_value_mismatch"
                    if same_doc
                    else "cross_document_discrepancy"
                )
                label = getattr(a, "seam_name", None) or getattr(a, "entity", None) or ek
                cid = f"geo:{ctype}:{a.document_id[:8]}:{b.document_id[:8]}:{metric}:{ek}:{bh or 'na'}"
                desc = (
                    f"Conflicting {metric} for {label}"
                    if same_doc
                    else f"Cross-document discrepancy for {metric} / {label}"
                )
                if ba or bb:
                    desc += f" (borehole {(ba or bb)})"
                desc += ". Human verification required — both sources shown."

                drafts.append(
                    GeologicalConflictDraft(
                        id=cid,
                        conflict_type=ctype,
                        entity_name=str(label) if label else None,
                        field_name=metric,
                        status="review_required",
                        severity="high" if same_doc else "medium",
                        description=desc,
                        requires_human_review=True,
                        evidence=[
                            {
                                "label": "A",
                                "document": a.document_name,
                                "document_id": a.document_id,
                                "page": a.page,
                                "value": a.value,
                                "unit": a.unit,
                                "seam_name": getattr(a, "seam_name", None),
                                "borehole_id": getattr(a, "borehole_id", None),
                                "formation": getattr(a, "geological_formation", None),
                                "evidence": a.evidence_text,
                                "status": a.status,
                                "fact_id": a.fact_id,
                                "is_calculated": False,
                            },
                            {
                                "label": "B",
                                "document": b.document_name,
                                "document_id": b.document_id,
                                "page": b.page,
                                "value": b.value,
                                "unit": b.unit,
                                "seam_name": getattr(b, "seam_name", None),
                                "borehole_id": getattr(b, "borehole_id", None),
                                "formation": getattr(b, "geological_formation", None),
                                "evidence": b.evidence_text,
                                "status": b.status,
                                "fact_id": b.fact_id,
                                "is_calculated": False,
                            },
                        ],
                    )
                )
    return drafts


def conflicts_as_dicts(hits: list, *, allow_cross_document: bool = True) -> list[dict[str, Any]]:
    return [
        d.to_dict()
        for d in detect_geological_conflicts(hits, allow_cross_document=allow_cross_document)
    ]
