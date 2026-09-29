"""Numerical comparison helpers (Phase 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import get_settings
from app.validation.rules import NormalizedUnit, to_base_value


@dataclass
class CompareResult:
    equal: bool
    conflict: bool
    unit_review: bool
    incompatible_units: bool
    left_base: Optional[float]
    right_base: Optional[float]
    abs_diff: Optional[float]
    left_unit: NormalizedUnit
    right_unit: NormalizedUnit


def values_within_tolerance(a: float, b: float) -> bool:
    settings = get_settings()
    abs_tol = settings.validation_absolute_tolerance
    rel_tol = settings.validation_relative_tolerance
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    scale = max(abs(a), abs(b), 1e-12)
    return (diff / scale) <= rel_tol


def compare_numeric(
    left_value: Optional[float],
    left_unit: Optional[str],
    right_value: Optional[float],
    right_unit: Optional[str],
) -> CompareResult:
    left_base, lu = to_base_value(left_value, left_unit)
    right_base, ru = to_base_value(right_value, right_unit)

    if left_base is None or right_base is None:
        return CompareResult(
            equal=False,
            conflict=False,
            unit_review=True,
            incompatible_units=False,
            left_base=left_base,
            right_base=right_base,
            abs_diff=None,
            left_unit=lu,
            right_unit=ru,
        )

    if lu.review_required or ru.review_required:
        return CompareResult(
            equal=False,
            conflict=False,
            unit_review=True,
            incompatible_units=False,
            left_base=left_base,
            right_base=right_base,
            abs_diff=abs(left_base - right_base),
            left_unit=lu,
            right_unit=ru,
        )

    if lu.compatible and ru.compatible and lu.canonical != ru.canonical:
        return CompareResult(
            equal=False,
            conflict=False,
            unit_review=True,
            incompatible_units=True,
            left_base=left_base,
            right_base=right_base,
            abs_diff=abs(left_base - right_base),
            left_unit=lu,
            right_unit=ru,
        )

    if not lu.compatible or not ru.compatible:
        return CompareResult(
            equal=False,
            conflict=False,
            unit_review=True,
            incompatible_units=True,
            left_base=left_base,
            right_base=right_base,
            abs_diff=abs(left_base - right_base),
            left_unit=lu,
            right_unit=ru,
        )

    equal = values_within_tolerance(left_base, right_base)
    return CompareResult(
        equal=equal,
        conflict=not equal,
        unit_review=False,
        incompatible_units=False,
        left_base=left_base,
        right_base=right_base,
        abs_diff=abs(left_base - right_base),
        left_unit=lu,
        right_unit=ru,
    )
