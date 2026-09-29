"""Semantic Analytics dimensions — separate Entity / Commodity / Metric / Measure.

Storage reality (unchanged):
- STRUCTURED_FACT chunk meta uses ``metric`` for both commodities (coal, lignite)
  and operational measures (overburden, dispatch). ``measurement_type`` holds
  during | upto | target.
- ExtractedFact uses ``field_name`` (production, production_target, coal, …)
  with no commodity column.

This module only *classifies* existing values for Analytics filters — no new tables.
"""

from __future__ import annotations

from typing import Optional

from app.validation.rules import normalize_field

# Stored as metric/field_name but are materials, not KPIs.
COMMODITY_FIELDS: frozenset[str] = frozenset(
    {
        "coal",
        "lignite",
        "coking_coal",
    }
)

# Operational KPIs (not materials).
OPERATIONAL_METRICS: frozenset[str] = frozenset(
    {
        "production",
        "overburden",
        "dispatch",
        "productivity",
        "power_generation",
        "achievement_percentage",
    }
)

# Field names that encode Measure=target rather than a separate measurement_type.
TARGET_FIELDS: frozenset[str] = frozenset(
    {
        "production_target",
    }
)

COMMODITY_LABELS: dict[str, str] = {
    "coal": "Coal",
    "lignite": "Lignite",
    "coking_coal": "Coking Coal",
}

MEASURE_LABELS: dict[str, str] = {
    "during": "Actual",
    "actual": "Actual",
    "upto": "Up to date",
    "target": "Target",
    "unknown": "Unknown",
}


def normalize_commodity(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if s in COMMODITY_FIELDS:
        return s
    for key, label in COMMODITY_LABELS.items():
        if label.lower() == raw.strip().lower():
            return key
    n = normalize_field(raw) or s
    return n if n in COMMODITY_FIELDS else None


def commodity_label(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return COMMODITY_LABELS.get(key, key.replace("_", " ").title())


def measure_label(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return MEASURE_LABELS.get(key, key.replace("_", " ").title())


def classify_raw_metric(
    raw_metric: Optional[str],
    *,
    measurement_type: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """Map stored metric/field_name (+ optional measure) into Analytics axes."""
    raw = (normalize_field(raw_metric) or (raw_metric or "").strip().lower()) or None
    measure = (measurement_type or "").strip().lower() or None
    if measure == "actual":
        measure = "during"

    if not raw:
        return {
            "commodity": None,
            "metric": None,
            "measure": measure,
            "storage_metric": None,
        }

    if raw in TARGET_FIELDS:
        return {
            "commodity": None,
            "metric": "production",
            "measure": "target",
            "storage_metric": raw,
        }

    if raw in COMMODITY_FIELDS:
        return {
            "commodity": raw,
            "metric": "production",
            "measure": measure or "during",
            "storage_metric": raw,
        }

    if raw in OPERATIONAL_METRICS:
        return {
            "commodity": None,
            "metric": raw,
            "measure": measure,
            "storage_metric": raw,
        }

    return {
        "commodity": None,
        "metric": raw,
        "measure": measure,
        "storage_metric": raw,
    }


def storage_metrics_for(
    *,
    commodity: Optional[str] = None,
    metric: Optional[str] = None,
    measure: Optional[str] = None,
) -> list[str]:
    """Stored metric/field_name values to query for a UI selection.

    Backward compatible: ``metric=coal`` still resolves to storage ``coal``.
    """
    c = normalize_commodity(commodity)
    m = (normalize_field(metric) or (metric or "").strip().lower()) or None
    meas = normalize_measure_param(measure)

    out: list[str] = []

    if m in COMMODITY_FIELDS:
        out.append(m)
        return out

    if meas == "target" and (m in {None, "production"} or m == "production_target"):
        out.append("production_target")
        if c:
            out.append(c)
        else:
            out.append("production")
        return list(dict.fromkeys(out))

    if c and (m in {None, "production"}):
        # Coal production tables store metric=coal; AI facts use production
        out.extend([c, "production"])
        return list(dict.fromkeys(out))

    if m:
        out.append(m)
        return out

    if c:
        out.append(c)
        return out

    return []


def normalize_measure_param(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if s in {"actual", "during"}:
        return "during"
    if s in {"target", "planned", "revised"}:
        return "target"
    if s in {"upto", "up_to"}:
        return "upto"
    return s
