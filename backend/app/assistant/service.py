"""Phase 6 assistant orchestration service."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.assistant.answer_generator import generate_answer
from app.assistant.chart_service import build_chart_spec
from app.assistant.citation_builder import build_chat_sources
from app.assistant.evidence_builder import EvidencePack
from app.assistant.query_router import parse_query, resolve_route, route_query
from app.assistant.rag_retriever import retrieve_rag_evidence
from app.assistant.structured_retriever import (
    StructuredFactHit,
    conflicts_for_structured,
    retrieve_structured_facts,
)
from app.config import get_settings
from app.validation.comparator import compare_numeric
from app.validation.rules import normalize_entity, normalize_field, normalize_period

_SESSIONS: dict[str, dict[str, Any]] = {}


@dataclass
class SessionCtx:
    entity: Optional[str] = None
    metric: Optional[str] = None
    history: deque = field(default_factory=lambda: deque(maxlen=8))


def _session(session_id: Optional[str]) -> tuple[str, SessionCtx]:
    sid = session_id or str(uuid4())
    raw = _SESSIONS.get(sid)
    if not raw:
        ctx = SessionCtx()
        _SESSIONS[sid] = {"ctx": ctx}
        return sid, ctx
    return sid, raw["ctx"]


def _dedupe_structured(hits: list[StructuredFactHit]) -> list[StructuredFactHit]:
    seen: set[str] = set()
    out: list[StructuredFactHit] = []
    for h in hits:
        key = f"{h.document_id}|{h.metric}|{h.period}|{h.value}|{h.unit}|{h.page}"
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def _group_conflicts_from_hits(hits: list[StructuredFactHit]) -> list[dict[str, Any]]:
    """Build conflict-like dicts when DB has disagreeing values but no Phase 5 row yet."""
    groups: dict[tuple[str, str, str], list[StructuredFactHit]] = {}
    for h in hits:
        e = normalize_entity(h.entity) or ""
        m = normalize_field(h.metric) or ""
        p = normalize_period(h.period) or ""
        if not e or not m:
            continue
        groups.setdefault((e, m, p), []).append(h)

    synthetic: list[dict[str, Any]] = []
    for (e, m, p), members in groups.items():
        reps: list[StructuredFactHit] = []
        for h in members:
            matched = False
            for r in reps:
                cmp = compare_numeric(h.numeric_value, h.unit, r.numeric_value, r.unit)
                if cmp.equal:
                    matched = True
                    break
            if not matched:
                reps.append(h)
        if len(reps) < 2:
            continue
        synthetic.append(
            {
                "id": f"synth:{e}:{m}:{p}",
                "conflict_type": "contradiction",
                "entity_name": reps[0].entity,
                "field_name": m,
                "period": p or None,
                "status": "review_required",
                "description": (
                    f"Multiple different {m} values for {reps[0].entity} {p or ''}. "
                    "Human verification required."
                ),
                "evidence": [
                    {
                        "label": chr(ord("A") + i),
                        "document": h.document_name,
                        "document_id": h.document_id,
                        "page": h.page,
                        "value": h.value,
                        "unit": h.unit,
                        "evidence": h.evidence_text,
                        "is_calculated": False,
                    }
                    for i, h in enumerate(reps[:6])
                ],
            }
        )
    return synthetic


def _probe_metrics(plan) -> list[Optional[str]]:
    metrics = list(plan.metrics or [])
    if plan.metric and plan.metric not in metrics:
        metrics.insert(0, plan.metric)
    specific = [m for m in metrics if m and m != "production"]
    if specific:
        return specific
    if metrics:
        return metrics
    return [plan.metric] if plan.metric else [None]


def ask_assistant(
    db: Session,
    question: str,
    *,
    session_id: Optional[str] = None,
    history: Optional[list[dict[str, str]]] = None,
) -> dict[str, Any]:
    settings = get_settings()
    sid, ctx = _session(session_id)
    if history:
        for turn in history[-settings.assistant_max_history :]:
            ctx.history.append(turn)

    plan = parse_query(
        question,
        prior_entity=ctx.entity,
        prior_metric=ctx.metric,
    )
    plan = resolve_route(db, plan)
    if plan.entity:
        ctx.entity = plan.entity
    if plan.metric:
        ctx.metric = plan.metric

    pack = EvidencePack(plan=plan)
    need_structured = plan.query_type in {"structured", "hybrid"}
    need_rag = plan.query_type in {"rag", "hybrid"}
    # Phase 7.1: comparisons need all compatible StructuredFact chunks from the index
    if getattr(plan, "comparison_mode", None):
        need_rag = True

    if need_structured:
        metrics = _probe_metrics(plan)
        all_hits: list[StructuredFactHit] = []
        all_conflicts = []
        for met in metrics:
            if not plan.entity and not met:
                continue
            all_conflicts.extend(
                conflicts_for_structured(
                    db,
                    entity=plan.entity,
                    metric=met,
                    periods=plan.periods or None,
                )
            )
            hits = retrieve_structured_facts(
                db,
                entity=plan.entity,
                metric=met,
                periods=plan.periods or None,
                verified_only=True,
            )
            if not hits and plan.periods and plan.entity:
                hits = retrieve_structured_facts(
                    db,
                    entity=plan.entity,
                    metric=met,
                    periods=None,
                    verified_only=True,
                )
                if hits:
                    pack.warnings.append("Requested period not found; showing related verified facts.")
            all_hits.extend(hits)

        pack.conflicts = all_conflicts
        if pack.conflicts:
            pack.warnings.append("Conflicting evidence found — no single verified value selected.")
            # Re-fetch without verified_only filter when conflicts exist
            all_hits = []
            for met in metrics:
                all_hits.extend(
                    retrieve_structured_facts(
                        db,
                        entity=plan.entity,
                        metric=met,
                        periods=plan.periods or None,
                        verified_only=False,
                    )
                )

        pack.structured = _dedupe_structured(all_hits)
        synthetic = _group_conflicts_from_hits(pack.structured)
        if synthetic and not pack.conflicts:
            pack.warnings.append("Multiple disagreeing values found for the same metric/period.")
            pack.meta_conflicts = synthetic

        # Evidence-aware fallback: routed structured but empty → try RAG
        if not pack.structured and not pack.conflicts and not getattr(pack, "meta_conflicts", None):
            need_rag = True
            if plan.query_type == "structured":
                plan.query_type = "rag"
                plan.route_reason = "structured_empty_fallback_rag"

    if need_rag or plan.query_type == "rag":
        rag_q = question
        if plan.entity and plan.entity.lower() not in question.lower():
            rag_q = f"{question} {plan.entity}"
        # Multi-entity: retrieve per entity and merge (strict compat still applied)
        entities = list(getattr(plan, "entities", None) or [])
        if len(entities) > 1:
            merged: dict[str, Any] = {}
            from app.assistant.rag_retriever import RagHit as _RH

            for ent in entities:
                sub = plan
                # shallow copy with single entity for filtering
                from dataclasses import replace

                sub_plan = replace(plan, entity=ent, entities=[ent])
                for hit in retrieve_rag_evidence(db, f"{rag_q} {ent}", plan=sub_plan):
                    prev = merged.get(hit.chunk_id)
                    if prev is None or (hit.score + hit.compat_score) > (
                        prev.score + prev.compat_score
                    ):
                        merged[hit.chunk_id] = hit
            pack.rag = sorted(
                merged.values(),
                key=lambda h: (h.score + h.compat_score),
                reverse=True,
            )[: max(12, settings.assistant_rag_top_k)]
        else:
            pack.rag = retrieve_rag_evidence(db, rag_q, plan=plan)
        if plan.query_type == "rag" and not pack.rag:
            pack.warnings.append(
                "No compatible document evidence matched this query "
                "(entity/metric/period). Index relevant reports first."
            )
            if plan.prefers_numeric and (plan.entity or plan.metrics):
                pack.warnings.append(
                    "Unrelated semantic matches were excluded - they do not support "
                    "the requested entity, metric, or period."
                )
        elif pack.rag and plan.periods and len(plan.periods) > 1:
            covered = {
                h.matched_period
                for h in pack.rag
                if getattr(h, "matched_period", None)
            }
            missing = [p for p in plan.periods if p not in covered]
            if missing and covered:
                pack.warnings.append(
                    "Evidence found for "
                    + ", ".join(sorted(covered))
                    + "; no compatible evidence for "
                    + ", ".join(missing)
                    + "."
                )
            elif missing and not covered:
                # Period tags may be absent on soft-filtered hits; still note multi-year ask
                pack.warnings.append(
                    "Multi-period query: verify each year independently in the citations."
                )

    # Phase 7.1 — multi-fact reasoning over verified STRUCTURED_FACT rag hits
    if getattr(plan, "comparison_mode", None) and plan.prefers_numeric:
        from app.assistant.multi_fact import (
            facts_from_rag_hits,
            format_multi_fact_answer,
            reason_over_facts,
        )

        facts = facts_from_rag_hits(pack.rag)
        mf = reason_over_facts(plan, facts)
        pack.multi_fact = mf.to_dict()
        if mf.status == "conflict":
            pack.warnings.append(
                "Multiple conflicting records were found for this requested value. "
                "Human verification is required."
            )
        elif mf.status in {"insufficient", "unit_mismatch"}:
            pack.warnings.append(mf.message or "Insufficient verified evidence for comparison.")
            # Clear rag numbers from answer path when comparison cannot be completed
            if mf.status == "insufficient" and not mf.facts:
                pack.rag = []

    if plan.want_chart and plan.entity and (plan.metric or plan.metrics) and not pack.conflicts:
        chart_metric = plan.metric or (plan.metrics[0] if plan.metrics else "production")
        chart_hits = pack.structured or retrieve_structured_facts(
            db,
            entity=plan.entity,
            metric=chart_metric,
            periods=plan.periods or None,
            verified_only=True,
        )
        pack.chart = build_chart_spec(
            chart_hits,
            entity=plan.entity,
            metric=chart_metric,
            chart_type="line",
        )

    if not pack.structured and not pack.rag and not pack.conflicts and not getattr(pack, "meta_conflicts", None):
        pack.warnings.append("Insufficient verified evidence.")

    answer = generate_answer(pack)
    synth = getattr(pack, "meta_conflicts", None) or []
    if synth and not pack.conflicts:
        extra = ["", "Multiple disagreeing values were found. Human verification is required."]
        for c in synth:
            extra.append("")
            extra.append(
                f"Conflict: {c.get('entity_name')} / {c.get('field_name')} / {c.get('period')}."
            )
            for e in c.get("evidence") or []:
                extra.append(
                    f"- Source {e.get('label')}: {e.get('document')} — Page {e.get('page')}: "
                    f"{e.get('value')} {e.get('unit') or ''}"
                )
            extra.append("Human verification is required before treating this value as authoritative.")
        answer = "\n".join(extra).strip() if plan.query_type == "structured" else (answer + "\n" + "\n".join(extra))

    sources = build_chat_sources(pack.structured, pack.rag, pack.conflicts)
    payload = pack.payload()
    if synth:
        payload["conflicts"] = list(payload.get("conflicts") or []) + synth
        if plan.query_type == "structured":
            payload["structured_evidence"] = []

    ctx.history.append({"role": "user", "content": question})
    ctx.history.append({"role": "assistant", "content": answer[:500]})

    return {
        "session_id": sid,
        "reply": answer,
        "answer": answer,
        "query_type": plan.query_type,
        "sources": sources,
        "structured_evidence": payload["structured_evidence"],
        "rag_evidence": payload["rag_evidence"],
        "conflicts": payload["conflicts"],
        "chart": payload["chart"],
        "warnings": payload["warnings"],
        "route_reason": plan.route_reason,
        "multi_fact": payload.get("multi_fact"),
        "comparison_mode": getattr(plan, "comparison_mode", None),
    }


def build_chart_only(
    db: Session,
    *,
    entity: Optional[str],
    metric: str = "production",
    question: Optional[str] = None,
) -> dict[str, Any]:
    plan = route_query(question or f"Show {entity or ''} {metric} trend", db=db)
    ent = entity or plan.entity
    met = metric or plan.metric or "production"
    hits = retrieve_structured_facts(db, entity=ent, metric=met, verified_only=True)
    conflicts = conflicts_for_structured(db, entity=ent, metric=met)
    chart = build_chart_spec(hits, entity=ent, metric=met)
    return {
        "entity": ent,
        "metric": met,
        "chart": chart,
        "conflicts": [
            {
                "id": c.id,
                "description": c.description,
                "status": c.status,
            }
            for c in conflicts
        ],
        "warnings": (
            ["Open validation conflicts exist for this metric — chart uses verified non-conflicting periods only."]
            if conflicts
            else []
        ),
    }
