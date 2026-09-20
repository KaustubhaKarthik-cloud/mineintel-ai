"""Confidence scoring for extracted mining facts."""

from __future__ import annotations

import re
from typing import Optional

from app.ai_extraction.schemas import ALLOWED_UNITS, LLMFactDraft
from app.config import get_settings


_OCR_SUSPICIOUS = re.compile(r"[0O]{2,}|[Il1]{3,}|\?|Pr0duct|M\?|rn|vv", re.I)
_NUMERIC_FIELD = {
    "production",
    "production_target",
    "achievement_percentage",
    "overburden",
    "lignite",
    "coal",
    "dispatch",
    "grade",
    "capacity",
    "reserves",
}


def score_fact(
    draft: LLMFactDraft,
    *,
    is_ocr_source: bool,
    schema_ok: bool,
    evidence_in_text: bool,
    ocr_mean_confidence: Optional[float] = None,
    ocr_low_confidence_decimals: Optional[list[str]] = None,
) -> float:
    """Engineering confidence indicator in [0, 1]."""
    score = 0.55

    if draft.value is not None and str(draft.value).strip() != "":
        score += 0.12
    if draft.evidence and len(draft.evidence.strip()) >= 8:
        score += 0.12
    if evidence_in_text:
        score += 0.10
    if draft.unit and draft.unit in ALLOWED_UNITS:
        score += 0.05
    if draft.mine or draft.entity:
        score += 0.04
    if draft.financial_year:
        score += 0.03
    if schema_ok:
        score += 0.06
    else:
        score -= 0.15

    if draft.ambiguous:
        score -= 0.22
    if is_ocr_source:
        score -= 0.10
        if draft.evidence and _OCR_SUSPICIOUS.search(draft.evidence):
            score -= 0.12
        if draft.evidence and "?" in draft.evidence:
            score -= 0.08
        if ocr_mean_confidence is not None and ocr_mean_confidence < 75:
            score -= 0.12
        if ocr_mean_confidence is not None and ocr_mean_confidence < 60:
            score -= 0.10
        val = str(draft.value or "").strip()
        lows = set(ocr_low_confidence_decimals or [])
        if val and any(val == d or val in d or d in val for d in lows):
            score -= 0.18

    if draft.field in _NUMERIC_FIELD and evidence_in_text:
        score += 0.04
        if is_ocr_source and (ocr_mean_confidence is None or ocr_mean_confidence < 80):
            score -= 0.05

    return max(0.0, min(1.0, round(score, 3)))


def classify_status(confidence: float) -> str:
    settings = get_settings()
    if confidence >= settings.high_confidence_threshold:
        return "high_confidence"
    if confidence < settings.review_threshold:
        return "review_required"
    return "review_required"
