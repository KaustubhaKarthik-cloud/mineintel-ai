"""Unit helpers — normalize only as additive fields; never replace originals."""

from __future__ import annotations

import re
from typing import Optional, Tuple


_DEPTH_THICKNESS_UNITS = {
    "m": "m",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "mt": "m",  # OCR confusion; treat carefully — only if context is depth/thickness
    "cm": "cm",
    "mm": "mm",
    "ft": "ft",
    "feet": "ft",
    "foot": "ft",
}


def parse_number(raw: str) -> Optional[float]:
    try:
        return float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def canonicalize_length_unit(unit: Optional[str]) -> Optional[str]:
    if not unit:
        return None
    key = re.sub(r"[^a-z]", "", unit.lower())
    return _DEPTH_THICKNESS_UNITS.get(key)


def to_metres(value: float, unit: Optional[str]) -> Optional[float]:
    """Additive normalization only."""
    u = canonicalize_length_unit(unit)
    if u is None:
        return None
    if u == "m":
        return value
    if u == "cm":
        return value / 100.0
    if u == "mm":
        return value / 1000.0
    if u == "ft":
        return value * 0.3048
    return None


def split_value_unit(token: str) -> Tuple[Optional[str], Optional[str]]:
    """Split '142.6 m' → ('142.6', 'm')."""
    m = re.match(
        r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*([A-Za-zµμ°/%]+)?\s*$",
        token or "",
    )
    if not m:
        return None, None
    return m.group(1).replace(",", ""), m.group(2)
