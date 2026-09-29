"""Phase 5 — deterministic field / entity / unit / period normalization rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

FIELD_ALIASES: dict[str, str] = {
    "production": "production",
    "annual_production": "production",
    "production_output": "production",
    "output": "production",
    "produced": "production",
    "production_qty": "production",
    "production_target": "production_target",
    "target_production": "production_target",
    "target": "production_target",
    "annual_target": "production_target",
    "achievement_percentage": "achievement_percentage",
    "achievement": "achievement_percentage",
    "achievement_pct": "achievement_percentage",
    "percent_achievement": "achievement_percentage",
    "dispatch": "dispatch",
    "grade": "grade",
    "ore_grade": "grade",
    "capacity": "capacity",
    "reserves": "reserves",
    "resources": "resources",
    "area": "area",
    "lease_area": "area",
    "overburden": "overburden",
    "lignite": "lignite",
    "coal": "coal",
}

# Canonical unit → multiplier to base tonnes (mass) or identity for percent
MASS_TO_TONNES: dict[str, float] = {
    "t": 1.0,
    "tonne": 1.0,
    "tonnes": 1.0,
    "ton": 1.0,
    "tons": 1.0,
    "kt": 1_000.0,
    "mt": 1_000_000.0,
    "million_tonnes": 1_000_000.0,
    "million tonnes": 1_000_000.0,
    "kg": 0.001,
}

PERCENT_UNITS = {"%", "pct", "percent", "percentage"}


@dataclass
class NormalizedUnit:
    canonical: str  # "tonnes" | "percent" | "unknown" | original
    multiplier_to_base: float
    compatible: bool
    review_required: bool = False


def normalize_field(field: Optional[str]) -> Optional[str]:
    if not field:
        return None
    key = re.sub(r"[\s\-]+", "_", field.strip().lower())
    key = re.sub(r"_+", "_", key)
    return FIELD_ALIASES.get(key, key)


def normalize_entity(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    text = name.strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[_\-/]+", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def entities_match(a: Optional[str], b: Optional[str]) -> str:
    """Return 'exact' | 'ambiguous' | 'different' | 'missing'."""
    na, nb = normalize_entity(a), normalize_entity(b)
    if not na or not nb:
        return "missing"
    if na == nb:
        return "exact"
    ta = {t for t in na.split() if len(t) > 1}
    tb = {t for t in nb.split() if len(t) > 1}
    if not ta or not tb:
        return "different"
    # Distinct trailing codes (mine a vs mine b) → different
    sa, sb = na.split(), nb.split()
    if len(sa) >= 2 and len(sb) >= 2 and sa[0] == sb[0] and sa[-1] != sb[-1] and len(sa[-1]) <= 2 and len(sb[-1]) <= 2:
        return "different"
    if ta <= tb or tb <= ta:
        return "ambiguous"
    overlap = ta & tb
    if len(overlap) >= 1 and (len(overlap) / max(len(ta), len(tb))) >= 0.6:
        # If non-overlapping tokens are short discriminators, treat as different
        only_a = ta - tb
        only_b = tb - ta
        if only_a and only_b and all(len(x) <= 2 for x in only_a | only_b):
            return "different"
        return "ambiguous"
    return "different"


def normalize_period(period: Optional[str]) -> Optional[str]:
    if not period:
        return None
    text = period.strip().upper().replace(" ", "")
    text = text.replace("–", "-").replace("—", "-")
    # FY2024 / FY 2024-25 / 2023-24 / 2023-2024
    m = re.match(r"^(?:FY)?(\d{4})(?:-(\d{2}|\d{4}))?$", text, re.I)
    if not m:
        return text.lower()
    start = m.group(1)
    end = m.group(2)
    if not end:
        return f"FY{start}"
    if len(end) == 2:
        return f"FY{start}-{end}"
    return f"FY{start}-{end[-2:]}"


def normalize_unit(unit: Optional[str]) -> NormalizedUnit:
    if not unit:
        return NormalizedUnit(canonical="unknown", multiplier_to_base=1.0, compatible=False, review_required=True)
    raw = unit.strip().lower()
    raw = raw.replace("million tonnes", "million_tonnes").replace("million tons", "million_tonnes")
    raw = re.sub(r"\s+", " ", raw)
    key = raw.replace(" ", "_") if "million" in raw else raw.replace(" ", "")

    if key in PERCENT_UNITS or raw in PERCENT_UNITS:
        return NormalizedUnit(canonical="percent", multiplier_to_base=1.0, compatible=True)

    for alias, mult in MASS_TO_TONNES.items():
        if key == alias or raw == alias:
            return NormalizedUnit(canonical="tonnes", multiplier_to_base=mult, compatible=True)

    # common OCR variants
    if key in {"m.t.", "m.t", "mt.", "mtonnes"}:
        return NormalizedUnit(canonical="tonnes", multiplier_to_base=1_000_000.0, compatible=True)

    return NormalizedUnit(canonical=raw, multiplier_to_base=1.0, compatible=False, review_required=True)


def to_base_value(numeric: Optional[float], unit: Optional[str]) -> tuple[Optional[float], NormalizedUnit]:
    nu = normalize_unit(unit)
    if numeric is None:
        return None, nu
    if not nu.compatible:
        return numeric, nu
    return numeric * nu.multiplier_to_base, nu
