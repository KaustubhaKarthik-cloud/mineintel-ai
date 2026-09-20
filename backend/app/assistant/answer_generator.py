"""Answer generation from evidence packs — never invents numbers."""

from __future__ import annotations

from app.assistant.evidence_builder import EvidencePack
from app.assistant.providers import LLMError, LLMProvider, MockLLMProvider, get_assistant_llm

SYSTEM_PROMPT = """You are MineIntel AI, an evidence-grounded mining document assistant.
Rules:
1. Answer ONLY using the supplied evidence.
2. Never invent numerical values, sources, or page numbers.
3. Never invent sources.
4. If evidence is insufficient, say you could not find verified evidence for the
   requested entity, metric, and period in the indexed documents.
5. If conflicting evidence exists, report BOTH sides and say human verification is required. Never pick a side.
6. Keep structured database evidence separate from document/RAG evidence.
7. Cite document name and page for every important factual claim.
8. Do not use outside world knowledge.
9. Do NOT treat a company as a state/region total, or lignite as coal, or one year as another.
10. Only cite sources that directly support the requested entity, metric, and period.
11. Never confuse reporting months (e.g. March vs December) or measure types (during vs upto).
12. Use only values whose reporting_period and measure fields match the question. If mapping is ambiguous, say so — do not guess.
13. If a relevant table was found but fiscal-year / reporting-period columns could not be mapped with confidence, say:
    "The relevant table was found, but the requested value could not be mapped to its fiscal-year/reporting-period column with sufficient confidence."
14. When MULTI-FACT REASONING RESULT is provided, use those pre-calculated values as-is.
    Do not recompute arithmetic. Do not invent missing years or entities.
"""


def _mock_answer(pack: EvidencePack) -> str:
    plan = pack.plan
    lines: list[str] = []

    # Phase 7.1: deterministic multi-fact answer takes precedence
    if pack.multi_fact and getattr(plan, "comparison_mode", None):
        from app.assistant.multi_fact import MultiFactResult, NormalizedFact, CalcResult, ConflictGroup, format_multi_fact_answer

        mf = pack.multi_fact
        result = MultiFactResult(
            status=mf.get("status") or "insufficient",
            facts=[NormalizedFact(**f) for f in (mf.get("facts") or [])],
            conflicts=[
                ConflictGroup(
                    dimension=c.get("dimension") or {},
                    facts=[NormalizedFact(**f) for f in (c.get("facts") or [])],
                )
                for c in (mf.get("conflicts") or [])
            ],
            calculation=CalcResult(**mf["calculation"]) if mf.get("calculation") else None,
            higher_label=mf.get("higher_label"),
            lower_label=mf.get("lower_label"),
            message=mf.get("message"),
        )
        return format_multi_fact_answer(plan, result)

    if pack.conflicts:
        lines.append("Two or more conflicting values were found. Human verification is required.")
        lines.append("I will not select a single authoritative number.")
        for c in pack.conflicts:
            lines.append("")
            lines.append(
                f"Conflict: {c.entity_name or 'entity'} / {c.field_name} / {c.period or 'period'} "
                f"({c.conflict_type})."
            )
            for e in c.evidence_items or []:
                loc = f"Page {e.page_number}" if e.page_number is not None else "Source n/a"
                lines.append(
                    f"- Source {e.label or ''}: {e.document_name} — {loc}: "
                    f"{e.value} {e.unit or ''}".strip()
                )
                if e.evidence_text:
                    lines.append(f"  Evidence: \"{e.evidence_text}\"")
        lines.append("")
        lines.append("Human verification is required before treating this value as authoritative.")
        if pack.chart is None and not pack.rag:
            return "\n".join(lines)

    if plan.query_type in {"structured", "hybrid"} and pack.structured and not pack.conflicts:
        lines.append("Structured data shows:")
        for h in pack.structured:
            loc = f"Page {h.page}" if h.page is not None else "source page n/a"
            lines.append(
                f"- {h.entity} {h.metric.replace('_', ' ')} {h.period or ''}: "
                f"{h.value} {h.unit or ''} "
                f"[{h.document_name}, {loc}] (status={h.status})"
            )
        lines.append("")

    if plan.query_type in {"rag", "hybrid"} and pack.rag:
        lines.append("The report / document evidence states:")
        for i, h in enumerate(pack.rag[:4], 1):
            loc = h.sheet_name or (f"Page {h.page}" if h.page is not None else "n/a")
            snippet = (h.text or "").strip()
            if len(snippet) > 280:
                snippet = snippet[:277] + "..."
            lines.append(f"- [{h.document_name}, {loc}] {snippet}")
        lines.append("")

    if pack.chart and pack.chart.get("data"):
        lines.append(
            f"Chart: {pack.chart.get('title')} "
            f"({pack.chart.get('x_axis')} vs {pack.chart.get('y_axis')})."
        )
        for row in pack.chart["data"]:
            lines.append(
                f"- {row.get('year')}: {row.get('value')} {row.get('unit') or ''} "
                f"(source {row.get('source')}, page {row.get('page')})"
            )
        lines.append("")

    if not lines:
        plan = pack.plan
        entity = plan.entity or "the requested entity"
        metrics = plan.metrics or ([plan.metric] if plan.metric else [])
        metric_label = ", ".join(m.replace("_", " ") for m in metrics) if metrics else "the requested metric"
        periods = plan.periods or []
        period_label = "/".join(periods) if periods else "the requested period"
        months = list(getattr(plan, "reporting_months", None) or [])
        if plan.prefers_numeric and (months or periods):
            return (
                "The relevant table was found, but the requested value could not be mapped "
                "to its fiscal-year/reporting-period column with sufficient confidence "
                f"for {entity} {metric_label} ({period_label}"
                + (f", {', '.join(months)}" if months else "")
                + "). "
                "I will not guess a number."
            )
        return (
            f"I couldn't find verified evidence for {entity} {metric_label} "
            f"for {period_label} in the indexed documents. "
            "Try indexing documents that explicitly cover this entity, metric, and period, "
            "or check Validation for conflicts."
        )

    if pack.warnings:
        lines.append("Warnings:")
        for w in pack.warnings:
            lines.append(f"- {w}")

    return "\n".join(lines).strip()


def generate_answer(pack: EvidencePack, provider: LLMProvider | None = None) -> str:
    llm = provider or get_assistant_llm()
    # Conflicts, multi-fact reasoning, and mock LLM: deterministic builder
    if (
        isinstance(llm, MockLLMProvider)
        or pack.conflicts
        or (pack.multi_fact and getattr(pack.plan, "comparison_mode", None))
    ):
        return _mock_answer(pack)
    try:
        user_prompt = (
            "Using ONLY the evidence below, write a concise answer with citations.\n"
            "If MULTI-FACT REASONING RESULT is present, report those numbers exactly.\n\n"
            + pack.to_prompt_context()
        )
        text = llm.generate(SYSTEM_PROMPT, user_prompt)
        if not (text or "").strip():
            return _mock_answer(pack)
        return text.strip()
    except LLMError:
        return _mock_answer(pack) + "\n\n(Note: external LLM unavailable; answered from evidence templates.)"
