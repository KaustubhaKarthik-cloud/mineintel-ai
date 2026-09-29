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
    document_id: Optional[str] = None
    geological_seam: Optional[str] = None
    geological_borehole: Optional[str] = None
    geological_formation: Optional[str] = None
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
    document_id: Optional[str] = None,
) -> dict[str, Any]:
    settings = get_settings()
    sid, ctx = _session(session_id)
    if history:
        for turn in history[-settings.assistant_max_history :]:
            ctx.history.append(turn)

    # Document switch: clear stale entity when the active document changes
    incoming_doc = (document_id or "").strip() or None
    if incoming_doc and ctx.document_id and incoming_doc != ctx.document_id:
        ctx.entity = None
        ctx.geological_seam = None
        ctx.geological_borehole = None
        ctx.geological_formation = None
    if incoming_doc:
        ctx.document_id = incoming_doc

    plan = parse_query(
        question,
        prior_entity=ctx.entity,
        prior_metric=ctx.metric,
        prior_seam=ctx.geological_seam,
        prior_borehole=ctx.geological_borehole,
        prior_formation=ctx.geological_formation,
    )
    plan = resolve_route(db, plan)
    if plan.entity:
        ctx.entity = plan.entity
    if plan.metric:
        ctx.metric = plan.metric
    if getattr(plan, "geological_seam", None):
        ctx.geological_seam = plan.geological_seam
    if getattr(plan, "geological_borehole", None):
        ctx.geological_borehole = plan.geological_borehole
    if getattr(plan, "geological_formation", None):
        ctx.geological_formation = plan.geological_formation

    pack = EvidencePack(plan=plan)
    need_structured = plan.query_type in {"structured", "hybrid"}
    need_rag = plan.query_type in {"rag", "hybrid"}
    skip_generic_rag = False
    # Phase 7.1: comparisons need all compatible StructuredFact chunks from the index
    if getattr(plan, "comparison_mode", None):
        need_rag = True

    # G1.1 / Master — geological hybrid: verified + unlabeled review_required + RAG
    if getattr(plan, "is_geological", False):
        from app.assistant.document_resolver import (
            dedupe_evidence_by_page_content,
            filter_hits_by_scope,
            log_scope_forensics,
            resolve_document_scope,
        )
        from app.assistant.geological_retriever import (
            detect_geological_conflicts,
            prefer_multi_seam_thickness,
            retrieve_geological_facts,
        )

        scope = resolve_document_scope(
            db,
            question=question,
            entity=plan.entity,
            entities=plan.entities,
            current_document_id=ctx.document_id,
            session_document_id=ctx.document_id,
            is_geological=True,
        )
        plan.document_scope_mode = scope.mode
        plan.scoped_document_ids = list(scope.allowed_ids)
        doc_ids = list(scope.allowed_ids)
        # CRITICAL: never convert empty allowed_ids → None for single-document /
        # deictic scopes (None means unrestricted multi-document RAG).
        scoped_retrieval = bool(
            doc_ids
            or scope.mode in {"single_document", "cross_document_comparison"}
            or scope.reason == "deictic_missing_current_document"
        )
        retrieval_ids: Optional[list[str]] = doc_ids if scoped_retrieval else (doc_ids or None)

        if scope.reason == "deictic_missing_current_document":
            pack.warnings.append(
                "This-report query needs a selected document. Choose a current "
                "document in the assistant, then ask again."
            )
        elif scope.primary_name:
            pack.warnings.append(f"Document scope: {scope.primary_name} ({scope.mode})")
        elif scope.mode == "single_document" and not doc_ids:
            pack.warnings.append(
                "This-report query needs a selected document. Open a document detail "
                "page or choose a current document in the assistant."
            )

        # When scoped to a current document, use its filename as entity for answer wording
        if scope.mode == "single_document" and scope.primary_name and (
            plan.deictic_document or not plan.entity
        ):
            # Strip extension for cleaner entity label
            import re as _re

            label = _re.sub(r"\.[A-Za-z0-9]{1,5}$", "", scope.primary_name)
            label = label.replace("_", " ").strip()
            plan.entity = label
            ctx.entity = label

        if retrieval_ids is not None and len(retrieval_ids) == 0:
            # Hard stop: deictic / single-doc with no allowed IDs — do not search all
            verified = []
            unverified_only = []
            geo_hits = []
            rejected_struct: list[str] = []
            struct_docs_before: list[str] = []
            pack.rag = []
            rag_docs_before: list[str] = []
            rejected_rag: list[str] = []
            rejected_all: list[str] = []
            rejection_reasons: list[str] = ["deictic_or_single_scope_empty"]
            primary_metric = (
                (getattr(plan, "geological_metrics", None) or plan.metrics or [None])[0]
            )
            skip_generic_rag = True
            need_rag = False
            need_structured = False
            _scope_forensics = {
                "scope": scope,
                "struct_docs": [],
                "rag_docs": [],
                "rejected": [],
                "rejection_reasons": rejection_reasons,
                "requested_metric": primary_metric,
                "requested_domain": getattr(plan, "domain", None) or "geological",
            }
        else:
            verified = retrieve_geological_facts(
                db,
                plan,
                verified_only=True,
                document_ids=retrieval_ids,
                limit=30,
            )
            unverified = retrieve_geological_facts(
                db,
                plan,
                verified_only=False,
                include_unverified=True,
                document_ids=retrieval_ids,
                limit=40,
            )
            # Keep unverified that aren't already in verified set
            verified_ids = {h.fact_id for h in verified}
            unverified_only = [h for h in unverified if h.fact_id not in verified_ids]
            # Prefer verified first; include unverified as extracted evidence (status preserved)
            geo_hits = prefer_multi_seam_thickness(verified + unverified_only, plan)
            if doc_ids:
                geo_hits, rejected_struct = filter_hits_by_scope(geo_hits, doc_ids)
            else:
                rejected_struct = []
            geo_hits = dedupe_evidence_by_page_content(geo_hits)
            struct_docs_before = list({h.document_name for h in geo_hits})

            if geo_hits:
                pack.structured = _dedupe_structured(list(pack.structured) + geo_hits)
                # Session follow-up memory: single unambiguous seam/borehole from hits
                seams_seen = {
                    h.seam_name for h in geo_hits if getattr(h, "seam_name", None)
                }
                if len(seams_seen) == 1:
                    ctx.geological_seam = next(iter(seams_seen))
                    plan.geological_seam = ctx.geological_seam
                bhs_seen = {
                    h.borehole_id for h in geo_hits if getattr(h, "borehole_id", None)
                }
                if len(bhs_seen) == 1:
                    ctx.geological_borehole = next(iter(bhs_seen))
                    plan.geological_borehole = ctx.geological_borehole
                geo_conflicts = detect_geological_conflicts(geo_hits)
                if geo_conflicts:
                    pack.meta_conflicts = list(getattr(pack, "meta_conflicts", None) or []) + geo_conflicts
                    has_mismatch = any(
                        (c.get("conflict_type") or "") == "geological_value_mismatch"
                        for c in geo_conflicts
                    )
                    has_disc = any(
                        (c.get("conflict_type") or "") == "cross_document_discrepancy"
                        for c in geo_conflicts
                    )
                    if has_mismatch:
                        pack.warnings.append(
                            "Conflicting geological values detected — human verification required."
                        )
                    if has_disc:
                        pack.warnings.append(
                            "Cross-document geological discrepancy detected — both sources shown; "
                            "not treated as automatic contradiction."
                        )
                # Soft validation of structured hits (never invents or auto-fixes)
                from app.geology.validation import validate_geological_hit

                for h in geo_hits:
                    for issue in validate_geological_hit(h):
                        if issue.severity == "high":
                            pack.warnings.append(f"Validation: {issue.message}")
                plan.query_type = "hybrid"
                plan.route_reason = (
                    "geological_verified_and_rag"
                    if verified
                    else "geological_unverified_structured_and_rag"
                )
                if unverified_only and not verified:
                    pack.warnings.append(
                        "Geological structured facts are pending review (not verified). "
                        "Treat them as extracted evidence only."
                    )
            need_structured = False  # skip mining ExtractedFact probe for geological asks

            from app.assistant.rag_retriever import retrieve_rag_evidence as _rag

            rag_q = question
            pack.rag = _rag(
                db,
                rag_q,
                plan=plan,
                document_ids=retrieval_ids,
                top_k=max(8, settings.assistant_rag_top_k),
            )
            rag_docs_before = list({h.document_name for h in pack.rag})
            if doc_ids:
                pack.rag, rejected_rag = filter_hits_by_scope(pack.rag, doc_ids)
            else:
                rejected_rag = []
            pack.rag = dedupe_evidence_by_page_content(pack.rag)
            rejected_all = list(dict.fromkeys(list(rejected_struct) + list(rejected_rag)))
            if rejected_all:
                pack.warnings.append(
                    "Rejected out-of-scope documents: " + ", ".join(rejected_all[:5])
                )

            # Listing-style geological asks: keep RAG supportive but shorter so structured IDs lead
            listing_intent = bool(getattr(plan, "listing_intent", False)) or (
                plan.geological_intent or ""
            ) in {
                "seam",
                "seam_listing",
                "borehole",
                "borehole_listing",
                "lithology",
                "lithology_listing",
                "formation",
                "formation_listing",
                "geological_structure",
                "seam_thickness",
                "seam_depth",
                "formation_thickness",
                "seam_parting_thickness",
                "borehole_depth",
            }
            if listing_intent and pack.structured and pack.rag:
                pack.rag = pack.rag[:4]

            # Final evidence gate: metric-kind compatibility (formation ≠ seam thickness)
            from app.geology.metric_kinds import (
                THICKNESS_METRICS,
                classify_evidence_metric_kind,
                metrics_compatible,
            )

            geo_metrics = list(
                getattr(plan, "geological_metrics", None)
                or plan.metrics
                or ([plan.metric] if plan.metric else [])
            )
            primary_metric = geo_metrics[0] if geo_metrics else None
            rejection_reasons = []
            if primary_metric and primary_metric in (
                THICKNESS_METRICS
                | {"seam_depth", "borehole_depth", "stratigraphic_depth"}
            ):
                from app.geology.metric_kinds import _METHODOLOGY_THICKNESS_RE, _SEAM_THICKNESS_RE
                from app.assistant.evidence_filter import evidence_compatible as _ec

                kept_rag = []
                for h in pack.rag:
                    txt = getattr(h, "text", None) or ""
                    # Named-seam thickness: re-check full compatibility (proximity + methodology)
                    if primary_metric == "seam_thickness" and getattr(
                        plan, "geological_seam", None
                    ):
                        if not _ec(plan, txt, require_metric=True).ok:
                            name = getattr(h, "document_name", None) or "?"
                            reason = (
                                f"{name}:p{getattr(h, 'page', '?')}:"
                                f"named_seam_thickness_incompatible"
                            )
                            rejection_reasons.append(reason)
                            if name not in rejected_all:
                                rejected_all.append(str(name))
                            continue
                    if (
                        primary_metric == "seam_thickness"
                        and _METHODOLOGY_THICKNESS_RE.search(txt)
                        and not _SEAM_THICKNESS_RE.search(txt)
                    ):
                        name = getattr(h, "document_name", None) or "?"
                        reason = (
                            f"{name}:p{getattr(h, 'page', '?')}:"
                            f"methodology_thickness!={primary_metric}"
                        )
                        rejection_reasons.append(reason)
                        if name not in rejected_all:
                            rejected_all.append(str(name))
                        continue
                    kind = classify_evidence_metric_kind(
                        text=txt,
                        has_thickness=False,
                        has_depth=False,
                        requested=primary_metric,
                    )
                    if metrics_compatible(primary_metric, kind):
                        kept_rag.append(h)
                    else:
                        name = getattr(h, "document_name", None) or "?"
                        reason = (
                            f"{name}:p{getattr(h, 'page', '?')}:"
                            f"{kind or 'unknown'}!={primary_metric}"
                        )
                        rejection_reasons.append(reason)
                        if name not in rejected_all:
                            rejected_all.append(str(name))
                pack.rag = kept_rag

                kept_struct = []
                for h in pack.structured:
                    kind = classify_evidence_metric_kind(
                        text=getattr(h, "evidence_text", None) or "",
                        seam_name=getattr(h, "seam_name", None),
                        borehole_id=getattr(h, "borehole_id", None),
                        has_thickness=h.metric in THICKNESS_METRICS
                        or bool(getattr(h, "value_min", None)),
                        has_depth=h.metric in {"seam_depth", "borehole_depth"},
                        requested=primary_metric,
                    )
                    if h.metric and h.metric == primary_metric:
                        kept_struct.append(h)
                    elif metrics_compatible(primary_metric, kind):
                        kept_struct.append(h)
                    else:
                        name = h.document_name or "?"
                        reason = f"{name}:p{h.page}:{kind or h.metric}!={primary_metric}"
                        rejection_reasons.append(reason)
                pack.structured = kept_struct

            # Absolute document-scope gate (never send out-of-scope evidence to Qwen)
            if doc_ids:
                pack.structured, rej_s = filter_hits_by_scope(pack.structured, doc_ids)
                pack.rag, rej_r = filter_hits_by_scope(pack.rag, doc_ids)
                for name in list(rej_s) + list(rej_r):
                    if name not in rejected_all:
                        rejected_all.append(str(name))
                        rejection_reasons.append(f"final_scope_reject:{name}")
                pack.structured = dedupe_evidence_by_page_content(pack.structured)
                pack.rag = dedupe_evidence_by_page_content(pack.rag)

            if not pack.rag and not pack.structured:
                if primary_metric == "seam_thickness":
                    pack.warnings.append(
                        "Compatible seam-thickness evidence was not found in the selected document."
                    )
                elif scope.mode == "single_document":
                    pack.warnings.append(
                        "Compatible evidence was not found in the selected document."
                    )
                else:
                    pack.warnings.append(
                        "No compatible document evidence matched this query "
                        "(entity/metric/period). Index relevant reports first."
                    )
            elif pack.rag and plan.query_type == "rag":
                plan.query_type = "hybrid"
                plan.route_reason = "geological_rag"
            skip_generic_rag = True
            need_rag = False

            _scope_forensics = {
                "scope": scope,
                "struct_docs": struct_docs_before,
                "rag_docs": rag_docs_before,
                "rejected": rejected_all,
                "rejection_reasons": rejection_reasons,
                "requested_metric": primary_metric,
                "requested_domain": getattr(plan, "domain", None) or "geological",
            }
    else:
        _scope_forensics = None

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

    if (need_rag or plan.query_type == "rag") and not skip_generic_rag:
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
        is_geo = bool(getattr(plan, "is_geological", False))
        extra = ["", "Conflicting evidence requires human verification. Both sources are shown."]
        for c in synth:
            ctype = c.get("conflict_type") or "geological_value_mismatch"
            label = "Cross-document discrepancy" if ctype == "cross_document_discrepancy" else "Conflict"
            extra.append("")
            extra.append(
                f"{label}: {c.get('entity_name')} / {c.get('field_name')}"
                + (f" / {c.get('period')}" if c.get("period") else "")
                + f" [{ctype}]."
            )
            for e in c.get("evidence") or []:
                extra.append(
                    f"- Source {e.get('label')}: {e.get('document')} — Page {e.get('page')}: "
                    f"{e.get('value')} {e.get('unit') or ''} (status={e.get('status')})"
                )
            extra.append("Human verification is required before treating either value as authoritative.")
        # Geological answers keep structured evidence visible alongside conflict notice
        if is_geo:
            answer = (answer + "\n" + "\n".join(extra)).strip()
        else:
            answer = (
                "\n".join(extra).strip()
                if plan.query_type == "structured"
                else (answer + "\n" + "\n".join(extra))
            )

    sources = build_chat_sources(pack.structured, pack.rag, pack.conflicts)
    payload = pack.payload()
    if synth:
        payload["conflicts"] = list(payload.get("conflicts") or []) + synth
        # Never wipe geological structured evidence when conflicts exist — show both sides
        if plan.query_type == "structured" and not getattr(plan, "is_geological", False):
            payload["structured_evidence"] = []

    ctx.history.append({"role": "user", "content": question})
    ctx.history.append({"role": "assistant", "content": answer[:500]})

    if _scope_forensics:
        from app.assistant.document_resolver import log_scope_forensics

        scope = _scope_forensics["scope"]
        final_docs = list(
            {
                *(h.document_name for h in pack.structured),
                *(h.document_name for h in pack.rag),
            }
        )
        final_pages = sorted(
            {
                *(h.page for h in pack.structured if h.page is not None),
                *(h.page for h in pack.rag if h.page is not None),
            }
        )
        final_metrics = list(
            {
                *(h.metric for h in pack.structured if h.metric),
            }
        )
        llm_meta = payload.get("llm_meta") or {}
        log_scope_forensics(
            query=question,
            scope=scope,
            structured_docs=_scope_forensics["struct_docs"],
            rag_docs=_scope_forensics["rag_docs"],
            rejected=_scope_forensics["rejected"],
            final_docs=final_docs,
            final_pages=final_pages,
            qwen_called=bool(llm_meta.get("called")),
            qwen_model=llm_meta.get("model"),
            requested_domain=_scope_forensics.get("requested_domain"),
            requested_metric=_scope_forensics.get("requested_metric"),
            rejection_reasons=_scope_forensics.get("rejection_reasons"),
            final_metrics=final_metrics,
            allowed_document_ids=list(scope.allowed_ids),
        )

    return {
        "session_id": sid,
        "reply": answer,
        "answer": answer,
        "query_type": plan.query_type,
        "domain": getattr(plan, "domain", None),
        "geological_intent": getattr(plan, "geological_intent", None),
        "is_geological": bool(getattr(plan, "is_geological", False)),
        "document_scope_mode": getattr(plan, "document_scope_mode", None),
        "document_id": ctx.document_id,
        "entity": plan.entity,
        "metrics": plan.metrics,
        "sources": sources,
        "structured_evidence": payload["structured_evidence"],
        "rag_evidence": payload["rag_evidence"],
        "conflicts": payload["conflicts"],
        "chart": payload["chart"],
        "warnings": payload["warnings"],
        "route_reason": plan.route_reason,
        "multi_fact": payload.get("multi_fact"),
        "comparison_mode": getattr(plan, "comparison_mode", None),
        "llm": payload.get("llm_meta"),
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
