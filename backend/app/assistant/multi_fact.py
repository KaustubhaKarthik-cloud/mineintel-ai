"""Phase 7.1 — multi-fact reasoning over verified StructuredFact evidence.

Deterministic grouping, conflict detection, and arithmetic. The LLM must only
explain results produced here — never invent missing values.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from app.assistant.query_router import QueryPlan
from app.assistant.rag_retriever import RagHit


@dataclass
class NormalizedFact:
    entity: str
    metric: str
    period: Optional[str]  # reporting month
    fy: str
    measure: str
    value: float
    unit: str
    source_document: Optional[str] = None
    page: Optional[int] = None
    table_title: Optional[str] = None
    column_path: Optional[str] = None
    chunk_id: Optional[str] = None

    def dimension_key(self) -> tuple:
        return (
            (self.entity or "").strip().lower(),
            (self.metric or "").strip().lower(),
            (self.period or "").strip().lower(),
            (self.fy or "").strip().upper().replace(" ", ""),
            (self.measure or "").strip().lower(),
            (self.unit or "").strip().lower(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalcResult:
    absolute_change: Optional[float]
    percentage_change: Optional[float]
    unit: str
    from_value: float
    to_value: float
    from_label: str
    to_label: str
    percent_undefined: bool = False  # true when denominator is zero

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConflictGroup:
    dimension: dict[str, Any]
    facts: list[NormalizedFact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "facts": [f.to_dict() for f in self.facts],
        }


@dataclass
class MultiFactResult:
    status: str  # ok | insufficient | conflict | unit_mismatch
    facts: list[NormalizedFact] = field(default_factory=list)
    conflicts: list[ConflictGroup] = field(default_factory=list)
    calculation: Optional[CalcResult] = None
    higher_label: Optional[str] = None
    lower_label: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "facts": [f.to_dict() for f in self.facts],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "calculation": self.calculation.to_dict() if self.calculation else None,
            "higher_label": self.higher_label,
            "lower_label": self.lower_label,
            "message": self.message,
        }


_FACT_RE = re.compile(
    r"STRUCTURED_FACT\s*\|\s*"
    r"entity=(?P<entity>[^|]+)\|\s*"
    r"metric=(?P<metric>[^|]+)\|\s*"
    r"reporting_period=(?P<period>[^|]+)\|\s*"
    r"measure=(?P<measure>[^|]+)\|\s*"
    r"fiscal_year=(?P<fy>[^|]+)\|\s*"
    r"value=(?P<value>[^|]+)\|\s*"
    r"unit=(?P<unit>[^|]+)",
    re.I,
)


def absolute_change(new_value: float, old_value: float) -> float:
    return float(new_value) - float(old_value)


def percentage_change(new_value: float, old_value: float) -> tuple[Optional[float], bool]:
    """Return (pct, undefined). undefined=True when old_value == 0."""
    old = float(old_value)
    if old == 0.0:
        return None, True
    return ((float(new_value) - old) / old) * 100.0, False


def units_compatible(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def parse_structured_fact_text(
    text: str,
    *,
    document_name: Optional[str] = None,
    page: Optional[int] = None,
    chunk_id: Optional[str] = None,
) -> Optional[NormalizedFact]:
    if not text or "STRUCTURED_FACT" not in text:
        return None
    m = _FACT_RE.search(text.replace("\n", " "))
    if not m:
        return None
    try:
        value = float(m.group("value").strip())
    except ValueError:
        return None
    table = None
    col = None
    tm = re.search(r"\|\s*table=([^|]+)", text, re.I)
    if tm:
        table = tm.group(1).strip()
    cm = re.search(r"\|\s*column=([^|]+)", text, re.I)
    if cm:
        col = cm.group(1).strip()
    pm = re.search(r"\|\s*page=(\d+)", text, re.I)
    page_from_text = int(pm.group(1)) if pm else page
    period = m.group("period").strip()
    if period.lower() == "unknown":
        period = None
    return NormalizedFact(
        entity=m.group("entity").strip(),
        metric=m.group("metric").strip(),
        period=period,
        fy=m.group("fy").strip().replace(" ", ""),
        measure=m.group("measure").strip().lower(),
        value=value,
        unit=m.group("unit").strip(),
        source_document=document_name,
        page=page_from_text if page_from_text is not None else page,
        table_title=table,
        column_path=col,
        chunk_id=chunk_id,
    )


def facts_from_rag_hits(hits: list[RagHit]) -> list[NormalizedFact]:
    out: list[NormalizedFact] = []
    for h in hits:
        fact = parse_structured_fact_text(
            h.text or "",
            document_name=h.document_name,
            page=h.page,
            chunk_id=h.chunk_id,
        )
        if fact:
            out.append(fact)
    return out


def _fy_sort_key(fy: str) -> int:
    m = re.search(r"(20)?(\d{2})", (fy or "").upper())
    if not m:
        return 0
    return int(m.group(2))


def _values_equal(a: float, b: float, *, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def resolve_unique_facts(facts: list[NormalizedFact]) -> tuple[list[NormalizedFact], list[ConflictGroup]]:
    """Collapse agreeing duplicates; surface conflicts for disagreeing same-dimension facts."""
    groups: dict[tuple, list[NormalizedFact]] = {}
    for f in facts:
        groups.setdefault(f.dimension_key(), []).append(f)

    unique: list[NormalizedFact] = []
    conflicts: list[ConflictGroup] = []
    for key, members in groups.items():
        reps: list[NormalizedFact] = []
        for f in members:
            if any(_values_equal(f.value, r.value) and units_compatible(f.unit, r.unit) for r in reps):
                continue
            reps.append(f)
        if len(reps) > 1:
            conflicts.append(
                ConflictGroup(
                    dimension={
                        "entity": members[0].entity,
                        "metric": members[0].metric,
                        "period": members[0].period,
                        "fy": members[0].fy,
                        "measure": members[0].measure,
                        "unit": members[0].unit,
                    },
                    facts=reps,
                )
            )
        else:
            # Prefer fact with a Table caption in title when duplicates agree
            best = max(
                members,
                key=lambda x: (
                    1 if x.table_title and re.search(r"table\s+\d", x.table_title or "", re.I) else 0,
                    -(x.page or 0),
                ),
            )
            unique.append(best)
    return unique, conflicts


def _required_slots(plan: QueryPlan) -> list[dict[str, Any]]:
    """Build the set of dimension slots the question needs filled."""
    entities = list(getattr(plan, "entities", None) or [])
    if not entities and plan.entity:
        entities = [plan.entity]
    periods = list(plan.periods or [])
    months = list(plan.reporting_months or [])
    measures = list(plan.measure_types or []) or ["during"]
    metrics = [m for m in (plan.metrics or ([plan.metric] if plan.metric else [])) if m]
    # Prefer specific metric over bare production
    specific = [m for m in metrics if m != "production"]
    if specific:
        metrics = specific

    slots: list[dict[str, Any]] = []
    if not entities or not metrics:
        return slots

    # Multi-entity × single FY (or all FYs) comparison
    mode = getattr(plan, "comparison_mode", None) or "compare"
    if len(entities) > 1:
        fys = periods or [None]
        for ent in entities:
            for fy in fys:
                for month in months or [None]:
                    for measure in measures:
                        for metric in metrics:
                            slots.append(
                                {
                                    "entity": ent,
                                    "metric": metric,
                                    "period": month,
                                    "fy": fy,
                                    "measure": measure,
                                }
                            )
        return slots

    # Single entity, multi-FY (YoY / change / which higher)
    if len(periods) >= 2 or mode in {"change", "rank", "compare"}:
        for fy in periods:
            for month in months or [None]:
                for measure in measures:
                    for metric in metrics:
                        slots.append(
                            {
                                "entity": entities[0],
                                "metric": metric,
                                "period": month,
                                "fy": fy,
                                "measure": measure,
                            }
                        )
        return slots

    # Single-slot fallback (not really multi-fact)
    for month in months or [None]:
        for measure in measures:
            for metric in metrics:
                slots.append(
                    {
                        "entity": entities[0],
                        "metric": metric,
                        "period": month,
                        "fy": periods[0] if periods else None,
                        "measure": measure,
                    }
                )
    return slots


def _fact_fills_slot(fact: NormalizedFact, slot: dict[str, Any], plan: QueryPlan) -> bool:
    from app.assistant.evidence_filter import text_matches_entity, period_match_forms

    if not text_matches_entity(fact.entity, slot.get("entity")):
        return False
    want_metric = (slot.get("metric") or "").lower()
    fm = (fact.metric or "").lower()
    if want_metric:
        if want_metric == "coal" and fm not in {"coal", "coal_production"}:
            return False
        if want_metric == "lignite" and fm != "lignite":
            return False
        if want_metric == "production":
            if "production" not in fm and fm not in {"coal", "lignite", "coking_coal"}:
                return False
        elif want_metric not in {"coal", "lignite", "production"}:
            if want_metric not in fm and fm not in want_metric:
                return False
    if slot.get("period") and (fact.period or "") != slot["period"]:
        return False
    if slot.get("measure") and (fact.measure or "").lower() != slot["measure"].lower():
        return False
    if slot.get("fy"):
        forms = {f.upper().replace(" ", "") for f in period_match_forms(slot["fy"])}
        forms |= {slot["fy"].upper().replace(" ", ""), slot["fy"].upper().replace(" ", "").replace("FY20", "FY")}
        fy = fact.fy.upper().replace(" ", "")
        if fy not in forms and fy.replace("FY20", "FY") not in forms:
            return False
    return True


def reason_over_facts(plan: QueryPlan, facts: list[NormalizedFact]) -> MultiFactResult:
    """Validate, group, and (when safe) calculate over verified facts."""
    unique, conflicts = resolve_unique_facts(facts)
    if conflicts:
        return MultiFactResult(
            status="conflict",
            facts=unique,
            conflicts=conflicts,
            message=(
                "Multiple conflicting records were found for this requested value. "
                "Human verification is required."
            ),
        )

    mode = getattr(plan, "comparison_mode", None)
    if not mode:
        # Not a multi-fact question — pass through
        return MultiFactResult(status="ok", facts=unique)

    slots = _required_slots(plan)
    if not slots:
        return MultiFactResult(
            status="insufficient",
            facts=unique,
            message="Insufficient evidence: could not determine the requested comparison dimensions.",
        )

    filled: list[tuple[dict[str, Any], NormalizedFact]] = []
    missing: list[dict[str, Any]] = []

    # Multi-entity without explicit FY: align on a common FY present for all entities.
    entities_needed = list(getattr(plan, "entities", None) or [])
    if len(entities_needed) > 1 and not plan.periods:
        from app.assistant.evidence_filter import text_matches_entity

        by_fy: dict[str, list[NormalizedFact]] = {}
        measures = list(plan.measure_types or []) or ["during"]
        months = list(plan.reporting_months or [])
        metrics = [m for m in (plan.metrics or ([plan.metric] if plan.metric else [])) if m]
        specific = [m for m in metrics if m != "production"]
        if specific:
            metrics = specific
        for f in unique:
            if months and f.period not in months:
                continue
            if measures and f.measure not in measures:
                continue
            if metrics and not any(
                (m == "coal" and f.metric in {"coal", "coal_production"})
                or m == f.metric
                or (
                    m == "production"
                    and (
                        "production" in f.metric
                        or f.metric in {"coal", "lignite", "coking_coal"}
                    )
                )
                or (m == "lignite" and f.metric == "lignite")
                for m in metrics
            ):
                continue
            if not any(text_matches_entity(f.entity, e) for e in entities_needed):
                continue
            by_fy.setdefault(f.fy, []).append(f)
        best_fy = None
        best_set: list[NormalizedFact] = []
        for fy, members in sorted(by_fy.items(), key=lambda kv: _fy_sort_key(kv[0]), reverse=True):
            covered = []
            for ent in entities_needed:
                hit = next((m for m in members if text_matches_entity(m.entity, ent)), None)
                if hit:
                    covered.append(hit)
            if len(covered) == len(entities_needed):
                best_fy = fy
                best_set = covered
                break
        if not best_set:
            return MultiFactResult(
                status="insufficient",
                facts=unique,
                message=(
                    "Insufficient verified evidence for the comparison. "
                    "Could not find a shared fiscal year covering all requested entities."
                ),
            )
        selected = best_set
        units = {(f.unit or "").lower() for f in selected}
        if len(units) > 1:
            return MultiFactResult(
                status="unit_mismatch",
                facts=selected,
                message="Unit mismatch across compared facts; cannot compute a change safely.",
            )
        ordered = sorted(selected, key=lambda f: f.value, reverse=True)
        calc = None
        if len(selected) == 2:
            abs_ch = absolute_change(ordered[0].value, ordered[-1].value)
            pct, undef = percentage_change(ordered[0].value, ordered[-1].value)
            calc = CalcResult(
                absolute_change=abs_ch,
                percentage_change=pct,
                unit=ordered[0].unit,
                from_value=ordered[-1].value,
                to_value=ordered[0].value,
                from_label=ordered[-1].entity,
                to_label=ordered[0].entity,
                percent_undefined=undef,
            )
        return MultiFactResult(
            status="ok",
            facts=selected,
            calculation=calc,
            higher_label=ordered[0].entity,
            lower_label=ordered[-1].entity,
            message=f"Aligned on {best_fy}." if best_fy else None,
        )

    for slot in slots:
        matches = [f for f in unique if _fact_fills_slot(f, slot, plan)]
        if not matches:
            missing.append(slot)
            continue
        filled.append((slot, matches[0]))

    if missing:
        return MultiFactResult(
            status="insufficient",
            facts=[f for _, f in filled],
            message=(
                "Insufficient verified evidence for the comparison. "
                "Missing required fact(s) for: "
                + "; ".join(
                    f"{s.get('entity')} {s.get('metric')} {s.get('period') or ''} "
                    f"{s.get('fy') or ''} {s.get('measure') or ''}".strip()
                    for s in missing[:4]
                )
            ),
        )

    selected = [f for _, f in filled]

    # Unit check across selected facts
    units = {(f.unit or "").lower() for f in selected}
    if len(units) > 1:
        return MultiFactResult(
            status="unit_mismatch",
            facts=selected,
            message="Unit mismatch across compared facts; cannot compute a change safely.",
        )

    entities = list({f.entity.strip().lower() for f in selected})
    calc: Optional[CalcResult] = None
    higher = lower = None

    if len(selected) >= 2 and len(entities) == 1 and len({f.fy for f in selected}) >= 2:
        ordered = sorted(selected, key=lambda f: _fy_sort_key(f.fy))
        old_f, new_f = ordered[0], ordered[-1]
        abs_ch = absolute_change(new_f.value, old_f.value)
        pct, undef = percentage_change(new_f.value, old_f.value)
        calc = CalcResult(
            absolute_change=abs_ch,
            percentage_change=pct,
            unit=new_f.unit,
            from_value=old_f.value,
            to_value=new_f.value,
            from_label=old_f.fy,
            to_label=new_f.fy,
            percent_undefined=undef,
        )
        if new_f.value > old_f.value:
            higher, lower = new_f.fy, old_f.fy
        elif old_f.value > new_f.value:
            higher, lower = old_f.fy, new_f.fy
        else:
            higher = lower = None

    elif len(selected) >= 2 and len(entities) > 1:
        # Entity comparison at aligned dimensions
        ordered = sorted(selected, key=lambda f: f.value, reverse=True)
        higher = ordered[0].entity
        lower = ordered[-1].entity
        if len(selected) == 2:
            a, b = selected[0], selected[1]
            # Treat first entity in plan.entities as "old"/left only for labeling; abs = a-b not meaningful
            # Prefer reporting both values; compute difference as higher - lower magnitude optional
            abs_ch = absolute_change(ordered[0].value, ordered[-1].value)
            pct, undef = percentage_change(ordered[0].value, ordered[-1].value)
            calc = CalcResult(
                absolute_change=abs_ch,
                percentage_change=pct,
                unit=ordered[0].unit,
                from_value=ordered[-1].value,
                to_value=ordered[0].value,
                from_label=ordered[-1].entity,
                to_label=ordered[0].entity,
                percent_undefined=undef,
            )

    return MultiFactResult(
        status="ok",
        facts=selected,
        calculation=calc,
        higher_label=higher,
        lower_label=lower,
    )


def format_multi_fact_answer(plan: QueryPlan, result: MultiFactResult) -> str:
    """Deterministic natural-language answer from reasoning result (no invented numbers)."""
    if result.status == "conflict":
        lines = [
            "Multiple conflicting records were found for this requested value. "
            "Human verification is required.",
            "",
        ]
        for cg in result.conflicts:
            d = cg.dimension
            lines.append(
                f"Conflict: {d.get('entity')} / {d.get('metric')} / "
                f"{d.get('period') or ''} / {d.get('fy')} / {d.get('measure')}."
            )
            for f in cg.facts:
                loc = f"page {f.page}" if f.page is not None else "page n/a"
                src = f.source_document or "document"
                table = f" ({f.table_title})" if f.table_title else ""
                lines.append(f"- {f.value:g} {f.unit} — {src}, {loc}{table}")
            lines.append("")
        lines.append("Human verification is required before treating this value as authoritative.")
        return "\n".join(lines).strip()

    if result.status in {"insufficient", "unit_mismatch"}:
        return result.message or "Insufficient verified evidence for this comparison."

    if not result.facts:
        return "Insufficient verified evidence for this comparison."

    mode = getattr(plan, "comparison_mode", None) or "compare"
    lines: list[str] = []

    # Header
    entities = list(dict.fromkeys(f.entity for f in result.facts))
    months = list(dict.fromkeys(f.period for f in result.facts if f.period))
    measures = list(dict.fromkeys(f.measure for f in result.facts if f.measure))
    metric = result.facts[0].metric
    month_bit = f" during {months[0]}" if len(months) == 1 else ""
    measure_bit = f" ({measures[0]})" if len(measures) == 1 and measures[0] else ""

    if len(entities) == 1:
        lines.append(f"{entities[0]} {metric.replace('_', ' ')}{month_bit}{measure_bit}:")
    else:
        lines.append(f"Comparison of {metric.replace('_', ' ')}{month_bit}{measure_bit}:")

    for f in sorted(result.facts, key=lambda x: (_fy_sort_key(x.fy), x.entity.lower())):
        label = f.fy if len(entities) == 1 else f"{f.entity} {f.fy}".strip()
        lines.append(f"- {label}: {f.value:g} {f.unit}")

    calc = result.calculation
    if calc and mode in {"compare", "change", "rank"}:
        lines.append("")
        if mode == "change" or (mode == "compare" and len(entities) == 1):
            lines.append(
                f"Change ({calc.from_label} → {calc.to_label}): {calc.absolute_change:g} {calc.unit}"
            )
            if calc.percent_undefined:
                lines.append(
                    "Percentage change: undefined (division by zero — baseline value is 0)."
                )
            elif calc.percentage_change is not None:
                lines.append(f"Percentage change: {calc.percentage_change:.2f}%")

    if mode == "rank" and result.higher_label:
        if result.lower_label and result.higher_label != result.lower_label:
            lines.append("")
            lines.append(
                f"{result.higher_label} was higher than {result.lower_label}."
            )
        else:
            lines.append("")
            lines.append(f"Values are equal ({result.higher_label}).")

    if mode == "compare" and len(entities) > 1 and result.higher_label:
        lines.append("")
        lines.append(
            f"{result.higher_label} is higher than {result.lower_label}."
        )

    lines.append("")
    lines.append("Evidence:")
    for f in result.facts:
        loc = f"page {f.page}" if f.page is not None else "page n/a"
        src = f.source_document or "document"
        table = f", {f.table_title}" if f.table_title else ""
        label = f.fy if len(entities) == 1 else f"{f.entity} {f.fy}"
        lines.append(f"- {label}: {src}{table}, {loc}")

    return "\n".join(lines).strip()
