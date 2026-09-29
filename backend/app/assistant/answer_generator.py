"""Answer generation from evidence packs — never invents numbers."""

from __future__ import annotations

import re

from app.assistant.evidence_builder import EvidencePack
from app.assistant.providers import LLMError, LLMProvider, LocalQwenProvider, MockLLMProvider, get_assistant_llm

SYSTEM_PROMPT = """You are MineIntel AI, an evidence-grounded mining document assistant.
Rules:
1. Answer ONLY using the supplied evidence.
2. Never invent numerical values, sources, page numbers, seam names, borehole IDs, or lithology.
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
15. For geological / exploration questions, use only geological evidence provided.
    Do not invent seam names, thicknesses, depths, or formations. Prefer citing the report page.
    If only review-pending structured facts exist and RAG evidence is present, rely on the RAG citations.
"""

GEOLOGICAL_SYSTEM_PROMPT = """You are MineIntel AI answering GEOLOGICAL / EXPLORATION questions.

You are answering using ONLY the supplied MineIntel evidence pack.
Treat the evidence as the ONLY source of truth.

Hard rules:
1. Do NOT use pretrained geological knowledge to fill gaps.
2. Do NOT invent seam names, borehole IDs, thicknesses, depths, lithology, formations, faults, resources, or pages.
3. Every factual claim MUST be supported by a supplied evidence item (structured fact or RAG excerpt).
4. Prefer evidence that explicitly names the requested geological concept (seams, boreholes, lithology, formations, etc.).
5. If an excerpt only says exploration happened but does not name seams/boreholes/etc., do NOT claim those values from it.
6. If structured facts are marked review_required or extracted, present them as extracted/unverified evidence — never call them verified.
7. If high_confidence/approved/corrected structured facts exist, you may treat them as verified structured evidence.
8. If evidence conflicts or shows a cross-document discrepancy, report BOTH sides and say human verification is required. Do not pick a winner.
9. If evidence is insufficient for the question, say: "Insufficient compatible evidence was found."
10. Cite DOCUMENT and PAGE for each important claim.
11. Quote or closely paraphrase seam/borehole/formation names EXACTLY as they appear in evidence.
12. Keep the answer concise and grounded.
13. Answer the USER QUESTION directly. If asked which boreholes are mentioned, list borehole IDs from evidence.
    If asked which seams are identified, list seam names (include uncorrelated/unnamed seams when present). If asked for thickness/depth, report those values with pages.
14. Do not digress into unrelated roof/floor/mining utilization content unless the question asks for it.
15. When a VALUE SUMMARY line is present, start your answer from those values, then cite supporting pages.
16. NEVER associate a thickness/depth value with a seam unless SEAM= is present on that fact (not n/a).
17. For multi-seam thickness questions, summarize EACH seam's thickness/range from structured facts — do not pick one arbitrary value.
18. Preserve numeric ranges exactly as written in evidence (e.g. 0.90–1.20 m). Do not invent averages or single values from ranges.
19. Preserve approximate (~) and inequality (<, >) qualifiers exactly. Do not convert them into exact values.
20. Do not convert units unless the evidence already states the converted value.
21. Never treat minimum workable thickness, formation thickness, parting thickness, or dirt-band thickness as seam thickness.
22. Only discuss documents present in the evidence pack. Never mention other indexed reports
    or claim insufficient evidence for documents the user did not ask about.
23. Never silently promote review_required facts to verified.
"""


def _mock_answer(pack: EvidencePack) -> str:
    plan = pack.plan
    lines: list[str] = []
    is_geo = bool(getattr(plan, "is_geological", False))

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

    if pack.meta_conflicts:
        lines.append("Conflicting geological values were found. Human verification is required.")
        for c in pack.meta_conflicts:
            lines.append(f"- {c.get('description')}")
            for e in c.get("evidence") or []:
                lines.append(
                    f"  [{e.get('label')}] {e.get('document')} page {e.get('page')}: "
                    f"{e.get('value')} {e.get('unit') or ''} (status={e.get('status')})"
                )
        lines.append("")

    if plan.query_type in {"structured", "hybrid"} and pack.structured and not pack.conflicts:
        verified = [h for h in pack.structured if h.status in {"high_confidence", "approved", "corrected"}]
        unverified = [h for h in pack.structured if h.status in {"review_required", "extracted"}]
        if verified:
            lines.append("Verified structured geological facts:" if is_geo else "Structured data shows:")
            for h in verified[:20]:
                loc = f"Page {h.page}" if h.page is not None else "source page n/a"
                seam = getattr(h, "seam_name", None)
                seam_bit = f"{seam} " if seam and is_geo else ""
                lines.append(
                    f"- {seam_bit}{h.metric.replace('_', ' ')}: {h.value} {h.unit or ''} "
                    f"[{h.document_name}, {loc}] (status={h.status})"
                )
            lines.append("")
        if unverified and is_geo:
            lines.append("Extracted geological facts (unverified — pending human review):")
            for h in unverified[:20]:
                loc = f"Page {h.page}" if h.page is not None else "source page n/a"
                seam = getattr(h, "seam_name", None)
                seam_bit = f"{seam} " if seam else ""
                lines.append(
                    f"- {seam_bit}{h.metric.replace('_', ' ')}: {h.value} {h.unit or ''} "
                    f"[{h.document_name}, {loc}] (status={h.status}, conf={h.confidence:.2f})"
                )
            lines.append("")
        elif not is_geo and pack.structured:
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
        if is_geo:
            lines.append("Geological / exploration document evidence states:")
        else:
            lines.append("The report / document evidence states:")
        for i, h in enumerate(pack.rag[:6], 1):
            loc = h.sheet_name or (f"Page {h.page}" if h.page is not None else "n/a")
            snippet = (h.text or "").strip()
            if len(snippet) > 320:
                snippet = snippet[:317] + "..."
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
        had_partial = bool(pack.rag or pack.structured) or any(
            "table" in (w or "").lower() or "mapped" in (w or "").lower()
            for w in (pack.warnings or [])
        )
        if is_geo:
            intent = getattr(plan, "geological_intent", None) or (
                (plan.metrics or [None])[0]
            )
            if intent == "seam_thickness":
                return (
                    "Compatible seam-thickness evidence was not found in the selected document."
                )
            return (
                "Insufficient compatible evidence was found for this geological question "
                f"({entity} / {metric_label}) in the indexed documents."
            )
        if plan.prefers_numeric and (months or periods) and had_partial:
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


def _geo_listing_lines(pack: EvidencePack) -> list[str]:
    """Deterministic listing from structured geo facts (status preserved)."""
    plan = pack.plan
    intent = getattr(plan, "geological_intent", None) or (
        plan.metrics[0] if plan.metrics else "value"
    )
    lines: list[str] = []
    seen: set[str] = set()
    for h in pack.structured:
        v = (h.value or "").strip()
        if not v:
            continue
        seam = (getattr(h, "seam_name", None) or "").strip()
        bh = (getattr(h, "borehole_id", None) or "").strip()
        key = f"{seam.lower()}|{bh.lower()}|{v.lower()}|{h.page}"
        if key in seen:
            continue
        seen.add(key)
        loc = f"page {h.page}" if h.page is not None else "page n/a"
        status_note = (
            "verified"
            if h.status in {"high_confidence", "approved", "corrected"}
            else f"extracted/unverified ({h.status})"
        )
        prefix = ""
        if intent in {"seam_thickness", "seam_depth"} and seam:
            prefix = f"{seam}: "
        elif intent in {"seam", "seam_listing"}:
            status = (getattr(h, "seam_status", None) or "").lower()
            if status in {"uncorrelated", "unnamed"} and not seam:
                prefix = ""
        elif bh and intent in {"borehole", "borehole_listing"}:
            prefix = ""
        unit = f" {h.unit}" if h.unit else ""
        lines.append(
            f"- {prefix}{v}{unit} [{h.document_name}, {loc}; {status_note}]"
        )
        if len(lines) >= 30:
            break
    if not lines:
        return []
    header = f"From structured geological evidence ({intent.replace('_', ' ')}):"
    return [header, *lines]


def _listing_intent(plan) -> bool:
    intent = getattr(plan, "geological_intent", None) or ""
    raw = (plan.raw_question or "").lower()
    if getattr(plan, "listing_intent", False):
        return True
    if intent in {
        "seam",
        "seam_listing",
        "borehole",
        "borehole_listing",
        "lithology",
        "lithology_listing",
        "formation",
        "formation_listing",
        "geological_structure",
        "coal_quality",
        "seam_thickness",
        "seam_depth",
        "formation_thickness",
        "seam_parting_thickness",
        "borehole_depth",
        "minimum_workable_seam_thickness",
    }:
        if re.search(
            r"\b(?:which|what|list|identify|identified|mentioned|present|reported|thickness|depth)\b",
            raw,
        ):
            return True
    return False


def generate_answer(pack: EvidencePack, provider: LLMProvider | None = None) -> str:
    llm = provider or get_assistant_llm()
    is_geo = bool(getattr(pack.plan, "is_geological", False))

    # No evidence → deterministic refusal (never let the LLM invent a soft paraphrase)
    if (
        not pack.structured
        and not pack.rag
        and not pack.conflicts
        and not pack.multi_fact
        and not getattr(pack, "meta_conflicts", None)
    ):
        pack.llm_meta = {"called": False, "provider": getattr(llm, "name", "none"), "reason": "no_evidence"}
        return _mock_answer(pack)

    # Conflicts, multi-fact reasoning, and mock LLM: deterministic builder
    if (
        isinstance(llm, MockLLMProvider)
        or pack.conflicts
        or (
            getattr(pack, "meta_conflicts", None)
            and not pack.structured  # if only conflicts, stay deterministic
        )
        or (pack.multi_fact and getattr(pack.plan, "comparison_mode", None))
    ):
        pack.llm_meta = {
            "called": False,
            "provider": getattr(llm, "name", "mock"),
            "reason": "mock_or_conflict_path",
        }
        return _mock_answer(pack)

    system = GEOLOGICAL_SYSTEM_PROMPT if is_geo else SYSTEM_PROMPT
    listing_prefix = ""
    if is_geo and _listing_intent(pack.plan) and pack.structured:
        listing_lines = _geo_listing_lines(pack)
        if listing_lines:
            listing_prefix = "\n".join(listing_lines) + "\n\n"
    if is_geo and getattr(pack, "meta_conflicts", None):
        conflict_note = (
            "IMPORTANT: Conflicting geological values exist for the same seam/context. "
            "Report BOTH sides and state that human verification is required. Do not pick one.\n\n"
        )
        listing_prefix = conflict_note + listing_prefix

    try:
        user_prompt = (
            "Using ONLY the evidence below, write a concise answer with DOCUMENT/PAGE citations.\n"
            "If MULTI-FACT REASONING RESULT is present, report those numbers exactly.\n"
            "If GEOLOGICAL domain: quote seam/borehole/formation names exactly as written in evidence.\n"
            "Prefer STRUCTURED GEOLOGICAL FACTS values (seam names, borehole IDs, thicknesses) when present; "
            "use RAG excerpts to support and cite pages. Answer the question directly — do not digress.\n"
        )
        if listing_prefix:
            user_prompt += (
                "CRITICAL: Begin with the structured value list below (do not replace it with roof/floor discussion).\n\n"
                + listing_prefix
            )
        user_prompt += "\n" + pack.to_prompt_context()
        text = llm.generate(system, user_prompt)
        model = getattr(llm, "_model", None) or getattr(llm, "model", None)
        pack.llm_meta = {
            "called": True,
            "provider": getattr(llm, "name", "unknown"),
            "model": model,
            "base_url": getattr(llm, "_base", None) if isinstance(llm, LocalQwenProvider) else None,
        }
        if not (text or "").strip():
            pack.llm_meta["reason"] = "empty_llm_response"
            return (listing_prefix + _mock_answer(pack)).strip() if listing_prefix else _mock_answer(pack)

        # Always lead listing-style answers with grounded structured values
        if listing_prefix:
            pack.llm_meta["listing_prefix"] = True
            # If LLM ignored most structured values, mark fallback; always keep list first
            values = [(h.value or "").strip() for h in pack.structured if h.value]
            uniq = []
            seen = set()
            for v in values:
                if v.lower() not in seen:
                    seen.add(v.lower())
                    uniq.append(v)
            hits = sum(1 for v in uniq[:10] if v.lower() in text.lower())
            need = min(3, len(uniq)) if uniq else 0
            if need and hits < need:
                pack.llm_meta["listing_fallback"] = True
            return (listing_prefix + "Narrative (from Qwen, evidence-grounded):\n" + text.strip()).strip()
        return text.strip()
    except LLMError as exc:
        pack.llm_meta = {
            "called": False,
            "provider": getattr(llm, "name", "unknown"),
            "error": str(exc),
            "reason": "llm_error_fallback_mock",
        }
        base = _mock_answer(pack)
        if listing_prefix:
            return listing_prefix + base + "\n\n(Note: external LLM unavailable; answered from evidence templates.)"
        return base + "\n\n(Note: external LLM unavailable; answered from evidence templates.)"
