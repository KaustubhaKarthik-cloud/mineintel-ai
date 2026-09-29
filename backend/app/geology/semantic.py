"""Shared geological semantic normalization for Analytics + Document Comparison.

Maps controlled aliases onto canonical metric_kind values.
Does not invent facts. Does not use unsafe substring entity matching.
"""

from __future__ import annotations

import re
from typing import Optional

from app.geology.metric_kinds import (
    BOREHOLE,
    BOREHOLE_DEPTH,
    COAL_QUALITY,
    FORMATION,
    FORMATION_THICKNESS,
    LITHOLOGY,
    MINIMUM_WORKABLE_SEAM_THICKNESS,
    RESERVE_QUANTITY,
    RESOURCE_QUANTITY,
    SEAM,
    SEAM_DEPTH,
    SEAM_THICKNESS,
    metrics_compatible,
)

# Controlled aliases only — exact / normalized key match, not loose substring.
_METRIC_ALIASES: dict[str, str] = {
    "minimum_workable_seam_thickness": MINIMUM_WORKABLE_SEAM_THICKNESS,
    "minimum_workable_thickness": MINIMUM_WORKABLE_SEAM_THICKNESS,
    "minimum workable thickness": MINIMUM_WORKABLE_SEAM_THICKNESS,
    "minimum workable seam thickness": MINIMUM_WORKABLE_SEAM_THICKNESS,
    "workable seam thickness": MINIMUM_WORKABLE_SEAM_THICKNESS,
    "workable_thickness": MINIMUM_WORKABLE_SEAM_THICKNESS,
    "min workable thickness": MINIMUM_WORKABLE_SEAM_THICKNESS,
    "min_workable_thickness": MINIMUM_WORKABLE_SEAM_THICKNESS,
    "seam_thickness": SEAM_THICKNESS,
    "seam thickness": SEAM_THICKNESS,
    "formation": FORMATION,
    "formations": FORMATION,
    "geological_formation": FORMATION,
    "formation_thickness": FORMATION_THICKNESS,
    "seam": SEAM,
    "seams": SEAM,
    "borehole": BOREHOLE,
    "boreholes": BOREHOLE,
    "borehole_id": BOREHOLE,
    "borehole_depth": BOREHOLE_DEPTH,
    "borehole_depths": BOREHOLE_DEPTH,
    "borehole depth": BOREHOLE_DEPTH,
    "seam_depth": SEAM_DEPTH,
    "resource": RESOURCE_QUANTITY,
    "resources": RESOURCE_QUANTITY,
    "resource_quantity": RESOURCE_QUANTITY,
    "seam resource": RESOURCE_QUANTITY,
    "seam_resource": RESOURCE_QUANTITY,
    "coal resource": RESOURCE_QUANTITY,
    "coal_resource": RESOURCE_QUANTITY,
    "geological resource": RESOURCE_QUANTITY,
    "reserve": RESERVE_QUANTITY,
    "reserves": RESERVE_QUANTITY,
    "reserve_quantity": RESERVE_QUANTITY,
    "lithology": LITHOLOGY,
    "coal_quality": COAL_QUALITY,
}

_DISPLAY_LABELS: dict[str, str] = {
    MINIMUM_WORKABLE_SEAM_THICKNESS: "Minimum Workable Seam Thickness",
    SEAM_THICKNESS: "Seam Thickness",
    FORMATION_THICKNESS: "Formation Thickness",
    FORMATION: "Formation",
    SEAM: "Seam",
    BOREHOLE: "Borehole",
    BOREHOLE_DEPTH: "Borehole Depth",
    SEAM_DEPTH: "Seam Depth",
    RESOURCE_QUANTITY: "Seam Resource",
    RESERVE_QUANTITY: "Reserve",
    LITHOLOGY: "Lithology",
    COAL_QUALITY: "Coal Quality",
}

_CANONICAL = frozenset(_DISPLAY_LABELS.keys()) | {
    FORMATION,
    SEAM,
    BOREHOLE,
    LITHOLOGY,
    COAL_QUALITY,
}

COMPARE_CATEGORIES: tuple[str, ...] = (
    "formations",
    "seams",
    "resources",
    "boreholes",
    "borehole_depths",
    "minimum_workable_thickness",
)

COMPARE_CATEGORY_TO_METRIC: dict[str, str] = {
    "formations": FORMATION,
    "seams": SEAM,
    "resources": RESOURCE_QUANTITY,
    "boreholes": BOREHOLE,
    "borehole_depths": BOREHOLE_DEPTH,
    "minimum_workable_thickness": MINIMUM_WORKABLE_SEAM_THICKNESS,
}

NO_COMPATIBLE_STRUCTURED = "No compatible structured evidence available."
NO_STRUCTURED_GEOLOGICAL = "No structured geological facts available for Analytics."

# Controlled recovery of numeric value from already-classified workable-thickness
# GeologicalFact rows whose thickness columns were left empty by older extracts.
# Only applied when metric_kind is already minimum_workable_seam_thickness.
_WORKABLE_VALUE_FROM_EVIDENCE_RE = re.compile(
    r"(?i)\bminimum\s+workable\s+thickness\b"
    r"[\s\S]{0,120}?"
    r"(?:(?:has\s+been\s+)?considered\s+(?:for\s+[^\.\n]{0,80}?)?)?"
    r"(?:is|of|=|:)?\s*"
    r"([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm)?"
)


def workable_thickness_value_from_fact(
    *,
    thickness: Optional[str] = None,
    thickness_unit: Optional[str] = None,
    thickness_min: Optional[str] = None,
    thickness_max: Optional[str] = None,
    corrected_value: Optional[str] = None,
    corrected_unit: Optional[str] = None,
    original_value: Optional[str] = None,
    original_unit: Optional[str] = None,
    evidence_text: Optional[str] = None,
    metric_kind: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return (value, unit) for a workable-thickness fact. Never invents a kind."""
    kind = normalize_geo_metric(metric_kind) or (metric_kind or "").strip().lower() or None
    if kind and kind != MINIMUM_WORKABLE_SEAM_THICKNESS:
        # Still allow structured fields if present; kind filter is caller's job
        pass
    if corrected_value:
        return str(corrected_value), corrected_unit or thickness_unit or original_unit
    if thickness:
        return str(thickness), thickness_unit
    if thickness_min and thickness_max:
        return f"{thickness_min}–{thickness_max}", thickness_unit
    if original_value:
        return str(original_value), original_unit or thickness_unit
    # Recover from evidence ONLY for already-classified workable thickness rows
    if kind == MINIMUM_WORKABLE_SEAM_THICKNESS and evidence_text:
        m = _WORKABLE_VALUE_FROM_EVIDENCE_RE.search(evidence_text)
        if m and m.group(1):
            return m.group(1).replace(",", "."), (m.group(2) or "m")
    return None, None


def _norm_key(raw: Optional[str]) -> str:
    s = (raw or "").strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def normalize_geo_metric(raw: Optional[str]) -> Optional[str]:
    """Map alias / display label → canonical metric_kind. Unknown → None."""
    if not raw:
        return None
    low = (raw or "").strip().lower()
    if low in _METRIC_ALIASES:
        return _METRIC_ALIASES[low]
    key = _norm_key(raw)
    if key in _METRIC_ALIASES:
        return _METRIC_ALIASES[key]
    if key in _CANONICAL:
        return key
    return None


def geo_metric_label(kind: Optional[str]) -> str:
    if not kind:
        return "Unknown"
    return _DISPLAY_LABELS.get(kind, kind.replace("_", " ").title())


def geo_metrics_compatible(requested: Optional[str], evidence_kind: Optional[str]) -> bool:
    """Compatibility after alias normalization — never broad substring matching."""
    req = normalize_geo_metric(requested) or ((requested or "").strip().lower() or None)
    ev = normalize_geo_metric(evidence_kind) or ((evidence_kind or "").strip().lower() or None)
    return metrics_compatible(req, ev)


def normalize_compare_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    low = raw.strip().lower()
    if low in COMPARE_CATEGORY_TO_METRIC:
        return low
    metric = normalize_geo_metric(raw)
    for cat, kind in COMPARE_CATEGORY_TO_METRIC.items():
        if metric == kind:
            return cat
    return None
