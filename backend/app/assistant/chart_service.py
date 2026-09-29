"""Chart data from verified structured facts only."""

from __future__ import annotations

from typing import Optional

from app.assistant.structured_retriever import StructuredFactHit


def build_chart_spec(
    hits: list[StructuredFactHit],
    *,
    entity: Optional[str],
    metric: Optional[str],
    chart_type: str = "line",
) -> Optional[dict]:
    # one value per period (prefer highest confidence)
    by_period: dict[str, StructuredFactHit] = {}
    for h in hits:
        if h.numeric_value is None or not h.period:
            continue
        prev = by_period.get(h.period)
        if prev is None or h.confidence >= prev.confidence:
            by_period[h.period] = h
    if len(by_period) < 2:
        # still allow single-point bar if at least one
        if not by_period:
            return None
    periods = sorted(by_period.keys())
    data = [
        {
            "year": p,
            "value": by_period[p].numeric_value,
            "unit": by_period[p].unit,
            "source": by_period[p].document_name,
            "page": by_period[p].page,
            "fact_id": by_period[p].fact_id,
        }
        for p in periods
    ]
    unit = next((d["unit"] for d in data if d.get("unit")), "")
    metric_label = (metric or "metric").replace("_", " ").title()
    return {
        "type": chart_type if len(data) >= 2 else "bar",
        "title": f"{entity or 'Entity'} {metric_label} Trend",
        "x_axis": "Financial Year",
        "y_axis": f"{metric_label}" + (f" ({unit})" if unit else ""),
        "data": data,
        "provenance": [
            {
                "year": d["year"],
                "document": d["source"],
                "page": d["page"],
                "value": d["value"],
                "unit": d["unit"],
            }
            for d in data
        ],
    }
