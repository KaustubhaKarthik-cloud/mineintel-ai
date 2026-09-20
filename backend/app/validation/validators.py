"""Derived-value validators (reported vs calculated)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.ai_extraction.validator import detect_achievement_discrepancy
from app.config import get_settings


@dataclass
class DiscrepancyResult:
    calculated: Optional[float]
    reported: Optional[float]
    difference_pp: Optional[float]
    detected: bool
    message: str


def check_achievement_discrepancy(
    production: Optional[float],
    target: Optional[float],
    reported_achievement: Optional[float],
) -> DiscrepancyResult:
    calculated, warning = detect_achievement_discrepancy(production, target, reported_achievement)
    if calculated is None or reported_achievement is None or not warning:
        return DiscrepancyResult(
            calculated=calculated,
            reported=reported_achievement,
            difference_pp=None,
            detected=False,
            message="",
        )
    diff = abs(calculated - reported_achievement)
    return DiscrepancyResult(
        calculated=calculated,
        reported=reported_achievement,
        difference_pp=diff,
        detected=True,
        message=(
            f"Reported achievement {reported_achievement}% differs from "
            f"calculated achievement {calculated}% "
            f"(Δ {diff:.2f} pp; tolerance {get_settings().achievement_discrepancy_tolerance} pp)."
        ),
    )
