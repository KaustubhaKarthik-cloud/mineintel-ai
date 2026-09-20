"""Generic evidence compatibility checks (entity / metric / period).

Used before RAG hits are passed to the LLM or shown as citations.
Does not hard-code companies, states, documents, or answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.assistant.query_router import QueryPlan


# Metrics that must not be treated as interchangeable without an explicit cue.
_METRIC_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "coal": ("lignite",),
    "lignite": ("coal production",),
    "overburden": (),
}


@dataclass
class CompatResult:
    ok: bool
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


def entity_tokens(entity: Optional[str]) -> list[str]:
    if not entity:
        return []
    raw = re.findall(r"[a-z0-9]{2,}", entity.lower())
    stop = {
        "the",
        "and",
        "of",
        "ltd",
        "limited",
        "company",
        "corp",
        "inc",
        "mine",
        "govt",
        "government",
    }
    return [t for t in raw if t not in stop]


def period_match_forms(period: str) -> list[str]:
    """Generate substrings that may appear in OCR/text for a requested period."""
    p = (period or "").upper().replace(" ", "")
    forms: list[str] = []
    m = re.fullmatch(r"FY(20)?(\d{2})(?:-(\d{2}|\d{4}))?", p)
    if not m:
        if period:
            forms.append(period.lower())
        return forms
    yy = m.group(2)
    end = m.group(3)
    full = f"20{yy}"
    forms.extend(
        [
            f"fy{full}".lower(),
            f"fy{yy}".lower(),
            f"fy {full}".lower(),
            f"fy {yy}".lower(),
            f"fy{full}",
            full,
        ]
    )
    try:
        prev = int(full) - 1
        forms.append(f"{prev}-{yy}")
        forms.append(f"{prev}/{yy}")
        forms.append(f"fy{prev}-{yy}".lower())
        forms.append(f"fy{full}-{yy}".lower())
        forms.append(f"{prev}–{yy}")
    except ValueError:
        pass
    if end:
        end2 = end[-2:] if len(end) == 4 else end
        forms.append(f"{full}-{end2}")
        forms.append(f"fy{full}-{end2}".lower())
    else:
        try:
            nxt = f"{(int(yy) + 1) % 100:02d}"
            forms.append(f"{full}-{nxt}")
            forms.append(f"{int(full)}-{nxt}")
        except ValueError:
            pass
    out: list[str] = []
    for f in forms:
        if f and f not in out:
            out.append(f)
    return out


def text_matches_any_period(hay: str, periods: list[str]) -> bool:
    if not periods:
        return True
    low = hay.lower()
    for p in periods:
        for form in period_match_forms(p):
            fl = form.lower()
            if not fl:
                continue
            if re.fullmatch(r"20\d{2}", fl):
                if re.search(rf"(?<!\d){re.escape(fl)}(?!\d)", low):
                    return True
                continue
            if fl in low:
                return True
    return False


def text_matches_entity(hay: str, entity: Optional[str]) -> bool:
    tokens = entity_tokens(entity)
    if not tokens:
        return True
    low = hay.lower()
    # Exact-ish label match first (handles Captive/Others vs Overall Captive & Others)
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

    ent_n = _norm(entity or "")
    hay_n = _norm(hay)
    if ent_n and hay_n == ent_n:
        return True
    # Word-boundary match so CIL does not match inside NLCIL.
    if len(tokens) == 1:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(tokens[0])}(?![a-z0-9])", low))
    return all(
        re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low) for t in tokens
    )


def text_matches_metric(hay: str, metrics: list[str]) -> bool:
    if not metrics:
        return True
    low = hay.lower()
    for m in metrics:
        m = (m or "").lower()
        if not m:
            continue
        if m == "production":
            if any(k in low for k in ("production", "produced", "output", "tonnage")):
                return True
            continue
        if m.replace("_", " ") in low or m in low:
            if m == "coal":
                if "coal" in low:
                    return True
                continue
            if m == "lignite" and "lignite" in low:
                return True
            if m not in {"coal", "lignite"}:
                return True
        if m == "coal" and re.search(r"\bcoal\b", low):
            return True
        if m == "lignite" and "lignite" in low:
            return True
        if m == "overburden" and "overburden" in low:
            return True
    return False


def entity_in_factual_role(hay: str, entity: Optional[str], metrics: list[str]) -> bool:
    """True when the entity appears as a production/metric subject, not only boilerplate."""
    tokens = entity_tokens(entity)
    if not tokens:
        return True
    low = (hay or "").lower()
    if len(tokens) == 1:
        if tokens[0] not in low:
            return False
        pattern = re.escape(tokens[0])
    else:
        if not all(t in low for t in tokens):
            return False
        pattern = r"\s+".join(re.escape(t) for t in tokens)

    metric_cues: list[str] = []
    for m in metrics or []:
        m = (m or "").lower()
        if m:
            metric_cues.append(m.replace("_", " "))
    metric_cues.extend(["production", "produced", "output", "tonnage", "dispatch"])

    for m in re.finditer(pattern, low):
        start, end = m.start(), m.end()
        window = low[max(0, start - 100) : min(len(low), end + 180)]
        ownership = bool(
            re.search(
                r"(?:govt\.?|government|joint\s+venture|equity|ministry)\s+(?:of\s+)?"
                + pattern,
                low[max(0, start - 48) : end + 48],
            )
        )
        has_number = bool(re.search(r"\d+\.\d+", window))
        has_metric = any(c in window for c in metric_cues)
        has_fy = bool(re.search(r"\bfy\s*2", window))
        reconstructed = bool(
            re.search(
                pattern + r"\s+(?:coal|lignite|overburden|production)\b.{0,100}fy\s*2",
                window,
            )
        )
        if reconstructed:
            return True
        if ownership and not (has_number and has_metric and "production" in window):
            continue
        # Row-like: entity beside a quantity and FY headers (common in table extracts)
        if has_number and has_fy and (has_metric or " mt" in window or window.strip().endswith("mt")):
            return True
        if has_number and has_metric:
            return True
    return False


def text_matches_reporting_month(hay: str, months: list[str]) -> bool:
    if not months:
        return True
    low = hay.lower()
    # Structured reconstructed form
    for month in months:
        mlow = month.lower()
        if f"reporting_period={mlow}" in low.replace(" ", ""):
            return True
        if f"reporting_period={month.lower()}" in low:
            return True
        if re.search(rf"reporting_period\s*=\s*{re.escape(month)}", hay, re.I):
            return True
        # Free text: during/upto March
        if re.search(rf"(?:during|upto|up\s*to|in)\s+{re.escape(month)}\b", low, re.I):
            return True
        # Abbreviation Mar/Dec in structured or header context
        abbrev = month[:3].lower()
        if re.search(rf"(?:during|upto)\s+{abbrev}\b", low, re.I):
            return True
    return False


def text_matches_measure_type(hay: str, measures: list[str]) -> bool:
    if not measures:
        return True
    low = hay.lower().replace(" ", "")
    raw = hay.lower()
    for m in measures:
        m = (m or "").lower()
        if m == "during":
            if "measure=during" in low:
                return True
            if re.search(r"\bduring\b", raw) and "measure=upto" not in low:
                return True
        if m == "upto":
            if "measure=upto" in low:
                return True
            if re.search(r"\bupto\b|\bup\s*to\b", raw):
                return True
    return False


def evidence_compatible(
    plan: QueryPlan,
    text: str,
    *,
    require_entity: bool = True,
    require_metric: bool = True,
    require_period: bool = False,
    active_periods: Optional[list[str]] = None,
    meta: Optional[dict] = None,
) -> CompatResult:
    """Score whether chunk text (or structured meta) can support the query plan."""
    if meta and meta.get("structured_fact"):
        return _structured_fact_compatible(
            plan,
            meta,
            text=text or "",
            require_entity=require_entity,
            require_metric=require_metric,
            require_period=require_period,
            active_periods=active_periods,
        )

    hay = text or ""
    reasons: list[str] = []
    score = 1.0

    entity_ok = text_matches_entity(hay, plan.entity)
    metrics = plan.metrics or ([plan.metric] if plan.metric else [])
    if require_entity and plan.entity and not entity_ok:
        return CompatResult(False, 0.0, ["entity_mismatch"])

    if (
        require_entity
        and plan.entity
        and entity_ok
        and (plan.prefers_numeric or metrics)
        and not entity_in_factual_role(hay, plan.entity, metrics)
    ):
        return CompatResult(False, 0.0, ["entity_not_factual_subject"])

    if plan.entity and entity_ok:
        score += 0.35
        reasons.append("entity_match")
    elif plan.entity and not entity_ok:
        score -= 0.5
        reasons.append("entity_absent")

    metric_ok = text_matches_metric(hay, metrics)
    if require_metric and metrics and not metric_ok:
        return CompatResult(False, 0.0, ["metric_mismatch"])
    if metrics and metric_ok:
        score += 0.25
        reasons.append("metric_match")

    periods = active_periods if active_periods is not None else plan.periods
    period_ok = text_matches_any_period(hay, periods)
    if require_period and periods and not period_ok:
        return CompatResult(False, 0.0, ["period_mismatch"])
    if periods and period_ok:
        score += 0.2
        reasons.append("period_match")
    elif periods and not period_ok:
        score -= 0.15
        reasons.append("period_absent")

    months = list(getattr(plan, "reporting_months", None) or [])
    if months:
        month_ok = text_matches_reporting_month(hay, months)
        if plan.prefers_numeric and not month_ok:
            return CompatResult(False, 0.0, ["reporting_month_mismatch"])
        if month_ok:
            score += 0.25
            reasons.append("reporting_month_match")

    measures = list(getattr(plan, "measure_types", None) or [])
    if measures and plan.prefers_numeric:
        measure_ok = text_matches_measure_type(hay, measures)
        if not measure_ok:
            return CompatResult(False, 0.0, ["measure_type_mismatch"])
        score += 0.1
        reasons.append("measure_type_match")

    if "coal" in metrics and "lignite" in hay.lower() and "coal" not in hay.lower():
        return CompatResult(False, 0.0, ["lignite_not_coal"])

    # Thermal coal queries must not use raw coking-coal tables as direct evidence.
    if "coal" in metrics and "coking" not in metrics:
        if re.search(r"\bcoking\s+coal\b", hay, re.I) and "reporting_period=" not in hay.lower():
            return CompatResult(False, 0.0, ["coking_not_thermal_coal"])

    return CompatResult(True, score, reasons)


def _fy_forms(period: str) -> set[str]:
    forms = set()
    for f in period_match_forms(period):
        forms.add(f.upper().replace(" ", ""))
        forms.add(f.upper().replace(" ", "").replace("FY20", "FY"))
    p = (period or "").upper().replace(" ", "")
    m = re.match(r"FY(?:20)?(\d{2})", p)
    if m:
        forms.add(f"FY{m.group(1)}")
        forms.add(f"FY20{m.group(1)}")
    return {x for x in forms if x}


def _structured_fact_compatible(
    plan: QueryPlan,
    meta: dict,
    *,
    text: str = "",
    require_entity: bool = True,
    require_metric: bool = True,
    require_period: bool = False,
    active_periods: Optional[list[str]] = None,
) -> CompatResult:
    """Validate STRUCTURED_FACT metadata — never infer from flattened OCR."""
    reasons: list[str] = []
    score = 1.2  # slight preference vs free-text when metadata matches
    entity = str(meta.get("entity") or "")
    metric = str(meta.get("metric") or "").lower()
    month = meta.get("reporting_month")
    fy = str(meta.get("fiscal_year") or "").upper().replace(" ", "")
    measure = str(meta.get("measurement_type") or "").lower()
    hay = f"{entity} {metric} {text}"

    if require_entity and plan.entity:
        # Structured facts: match the row entity only — never the table title / page text
        # Prefer normalized label equality so partial names don't bind the wrong row.
        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

        if _norm(entity) == _norm(plan.entity):
            reasons.append("entity_match")
            score += 0.35
        elif text_matches_entity(entity, plan.entity) and (
            # Allow only when plan entity is not a strict shorter prefix of a longer label
            # (e.g. "Captive" must not satisfy "Overall Captive & Others" when a more
            # precise label exists — require plan covers all significant tokens of entity
            # OR entity tokens ⊆ plan tokens with equal count).
            len(entity_tokens(entity)) <= len(entity_tokens(plan.entity))
        ):
            reasons.append("entity_match")
            score += 0.35
        else:
            return CompatResult(False, 0.0, ["entity_mismatch"])

    metrics = [m.lower() for m in (plan.metrics or ([plan.metric] if plan.metric else [])) if m]
    if require_metric and metrics:
        ok = False
        for m in metrics:
            ml = m.replace("_", " ")
            if m == "coal" and metric in {"coal", "coal_production"}:
                ok = True
            elif ml in metric.replace("_", " ") or m == metric:
                ok = True
            elif m == "production" and (
                "production" in metric or metric in {"coal", "lignite", "coking_coal"}
            ):
                ok = True
            elif m == "lignite" and metric == "lignite":
                ok = True
        if not ok:
            return CompatResult(False, 0.0, ["metric_mismatch"])
        if "coal" in metrics and metric == "lignite":
            return CompatResult(False, 0.0, ["lignite_not_coal"])
        if "coal" in metrics and metric == "coking_coal":
            return CompatResult(False, 0.0, ["coking_not_thermal_coal"])
        reasons.append("metric_match")
        score += 0.25

    periods = active_periods if active_periods is not None else plan.periods
    if periods:
        fy_ok = any(fy in _fy_forms(p) or fy.replace("FY20", "FY") in _fy_forms(p) for p in periods)
        if require_period and not fy_ok:
            return CompatResult(False, 0.0, ["period_mismatch"])
        if fy_ok:
            reasons.append("period_match")
            score += 0.2
        elif require_period:
            return CompatResult(False, 0.0, ["period_mismatch"])
        else:
            score -= 0.15
            reasons.append("period_absent")

    months = list(getattr(plan, "reporting_months", None) or [])
    if months:
        if not month or month not in months:
            if plan.prefers_numeric:
                return CompatResult(False, 0.0, ["reporting_month_mismatch"])
        else:
            reasons.append("reporting_month_match")
            score += 0.25

    measures = list(getattr(plan, "measure_types", None) or [])
    if measures and plan.prefers_numeric:
        if measure not in measures:
            return CompatResult(False, 0.0, ["measure_type_mismatch"])
        reasons.append("measure_type_match")
        score += 0.15

    return CompatResult(True, score, reasons)
