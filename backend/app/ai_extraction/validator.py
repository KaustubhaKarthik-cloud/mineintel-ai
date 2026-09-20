"""Deterministic validation for extracted facts."""

from __future__ import annotations

import re
from typing import Any, Optional

from app.ai_extraction.schemas import ALLOWED_FIELDS, ALLOWED_UNITS, LLMFactDraft
from app.config import get_settings

FY_RE = re.compile(r"^(FY\s?)?\d{4}([-/]\d{2})?$", re.I)
NUMERIC_FIELDS = {
    "production",
    "production_target",
    "achievement_percentage",
    "dispatch",
    "grade",
    "capacity",
    "reserves",
    "resources",
    "area",
}


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    text = re.sub(r"[^\d.\-]", "", text)
    try:
        return float(text)
    except ValueError:
        return None


def validate_draft(draft: LLMFactDraft, source_text: str) -> tuple[bool, list[str], Optional[float]]:
    """Return (ok, warnings, numeric_value)."""
    warnings: list[str] = []
    field = (draft.field or "").strip().lower().replace(" ", "_")
    if field not in ALLOWED_FIELDS:
        warnings.append(f"Unknown field '{draft.field}' rejected.")
        return False, warnings, None

    draft.field = field
    numeric = _to_float(draft.value) if draft.value is not None else None

    if field in NUMERIC_FIELDS:
        if numeric is None:
            warnings.append(f"Field '{field}' requires a numeric value.")
            return False, warnings, None
        if field == "achievement_percentage" and not (0 <= numeric <= 150):
            warnings.append("Achievement percentage out of reasonable bounds.")
            return False, warnings, numeric
        if field in {"grade"} and not (0 <= numeric <= 100):
            warnings.append("Grade percentage out of reasonable bounds.")
            return False, warnings, numeric

    if draft.unit and draft.unit not in ALLOWED_UNITS:
        warnings.append(f"Unusual unit '{draft.unit}'.")

    if draft.financial_year and not FY_RE.match(str(draft.financial_year).replace(" ", "")):
        warnings.append(f"Unusual financial year format '{draft.financial_year}'.")

    if not draft.evidence or not str(draft.evidence).strip():
        warnings.append("Missing evidence text.")
        return False, warnings, numeric

    # Evidence should appear in source (loose check)
    ev = str(draft.evidence).strip()
    if ev and ev.lower() not in source_text.lower():
        # allow partial overlap
        tokens = [t for t in re.split(r"\s+", ev) if len(t) > 3][:4]
        if tokens and not any(t.lower() in source_text.lower() for t in tokens):
            warnings.append("Evidence text not found in source page.")
            return False, warnings, numeric

    return True, warnings, numeric


def detect_achievement_discrepancy(
    production: Optional[float],
    target: Optional[float],
    reported_achievement: Optional[float],
) -> tuple[Optional[float], Optional[str]]:
    """Return (calculated_pct, warning) without overwriting reported values."""
    if production is None or target is None or target == 0:
        return None, None
    calculated = round((production / target) * 100.0, 2)
    if reported_achievement is None:
        return calculated, None
    tol = get_settings().achievement_discrepancy_tolerance
    if abs(calculated - reported_achievement) > tol:
        return (
            calculated,
            (
                f"Reported achievement ({reported_achievement}%) differs from "
                f"calculated achievement ({calculated}%)."
            ),
        )
    return calculated, None
