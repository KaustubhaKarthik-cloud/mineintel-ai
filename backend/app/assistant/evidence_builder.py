"""Build evidence packs for the LLM / mock answer generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.assistant.citation_builder import conflict_to_dict, rag_to_dict, structured_to_dict
from app.assistant.query_router import QueryPlan
from app.assistant.rag_retriever import RagHit
from app.assistant.structured_retriever import StructuredFactHit
from app.models import ValidationConflict


@dataclass
class EvidencePack:
    plan: QueryPlan
    structured: list[StructuredFactHit] = field(default_factory=list)
    rag: list[RagHit] = field(default_factory=list)
    conflicts: list[ValidationConflict] = field(default_factory=list)
    chart: Optional[dict[str, Any]] = None
    warnings: list[str] = field(default_factory=list)
    meta_conflicts: list[dict[str, Any]] = field(default_factory=list)
    multi_fact: Optional[dict[str, Any]] = None
    llm_meta: Optional[dict[str, Any]] = None

    def to_prompt_context(self) -> str:
        is_geo = bool(getattr(self.plan, "is_geological", False))
        blocks = [
            f"QUESTION: {self.plan.raw_question}",
            f"QUERY_TYPE: {self.plan.query_type}",
            f"DOMAIN: {getattr(self.plan, 'domain', 'general')}",
            f"GEOLOGICAL_INTENT: {getattr(self.plan, 'geological_intent', None) or 'n/a'}",
            f"ENTITY: {self.plan.entity or 'n/a'}",
            f"METRICS: {', '.join(self.plan.metrics or []) or 'n/a'}",
            "",
        ]
        if self.multi_fact:
            blocks.append("MULTI-FACT REASONING RESULT (pre-calculated; do not recompute or invent):")
            blocks.append(str(self.multi_fact))
            blocks.append("")
        if self.conflicts:
            blocks.append("CONFLICTS (do not pick a side):")
            for c in self.conflicts:
                blocks.append(f"- {c.description}")
                for e in c.evidence_items or []:
                    blocks.append(
                        f"  [{e.label}] {e.document_name} page {e.page_number}: "
                        f"{e.value} {e.unit or ''} | {e.evidence_text or ''}"
                    )
            blocks.append("")
        if self.meta_conflicts:
            blocks.append("GEOLOGICAL / META CONFLICTS (do not pick a side):")
            for c in self.meta_conflicts:
                blocks.append(f"- {c.get('description')}")
                for e in c.get("evidence") or []:
                    blocks.append(
                        f"  [{e.get('label')}] {e.get('document')} page {e.get('page')}: "
                        f"{e.get('value')} {e.get('unit') or ''} status={e.get('status')} "
                        f"| {e.get('evidence') or ''}"
                    )
            blocks.append("")
        if self.structured:
            if is_geo:
                blocks.append(
                    "STRUCTURED GEOLOGICAL FACTS "
                    "(status high_confidence/approved/corrected = verified; "
                    "review_required/extracted = unverified extracted evidence — label clearly). "
                    "Associate a value with a seam/borehole ONLY when that field is present:"
                )
                intent = getattr(self.plan, "geological_intent", None) or (
                    self.plan.metrics[0] if self.plan.metrics else None
                )
                vals: list[str] = []
                seen_v: set[str] = set()
                for h in self.structured:
                    v = (h.value or "").strip()
                    if not v:
                        continue
                    seam = (getattr(h, "seam_name", None) or "").strip()
                    key = f"{seam.lower()}|{v.lower()}"
                    if key in seen_v:
                        continue
                    seen_v.add(key)
                    page = f"p.{h.page}" if h.page is not None else "p.?"
                    label = f"{seam}: {v}" if seam else v
                    vals.append(f"{label} ({h.document_name}, {page}, status={h.status})")
                    if len(vals) >= 25:
                        break
                if vals and intent:
                    blocks.append(
                        f"VALUE SUMMARY for intent={intent} (use these names/IDs when listing): "
                        + "; ".join(vals)
                    )
                for h in self.structured:
                    seam = getattr(h, "seam_name", None) or "n/a"
                    bh = getattr(h, "borehole_id", None) or "n/a"
                    if getattr(h, "value_min", None) and getattr(h, "value_max", None):
                        range_s = f"{h.value_min}–{h.value_max}"
                    else:
                        range_s = h.value or "n/a"
                    blocks.append(
                        f"- DOCUMENT={h.document_name} | DOCUMENT_ID={h.document_id} | "
                        f"FORMATION={getattr(h, 'geological_formation', None) or 'n/a'} | "
                        f"SEAM={seam} | SEAM_STATUS={getattr(h, 'seam_status', None) or 'n/a'} | "
                        f"BOREHOLE={bh} | "
                        f"METRIC={h.metric} | RANGE_OR_VALUE={range_s} | UNIT={h.unit or ''} | "
                        f"PAGE={h.page} | STATUS={h.status} | CONFIDENCE={h.confidence:.2f} | "
                        f"FACT_ID={h.fact_id} | "
                        f"EVIDENCE={h.evidence_text or ''}"
                    )
            else:
                blocks.append("VERIFIED STRUCTURED EVIDENCE:")
                for h in self.structured:
                    blocks.append(
                        f"- DOCUMENT={h.document_name} | PAGE={h.page} | METRIC={h.metric} | "
                        f"VALUE={h.value} | UNIT={h.unit or ''} | STATUS={h.status} | "
                        f"CONFIDENCE={h.confidence:.2f} | EVIDENCE={h.evidence_text or ''}"
                    )
            blocks.append("")
        if self.rag:
            if is_geo:
                blocks.append(
                    "GEOLOGICAL DOCUMENT / RAG EVIDENCE "
                    "(use only claims supported by these excerpts; cite DOCUMENT + PAGE):"
                )
            else:
                blocks.append("DOCUMENT / RAG EVIDENCE:")
            for i, h in enumerate(self.rag, 1):
                loc = h.sheet_name or (f"page {h.page}" if h.page is not None else "n/a")
                snippet = (h.text or "")[:900]
                blocks.append(
                    f"- [R{i}] DOCUMENT={h.document_name} | PAGE={loc} | "
                    f"SCORE={h.score:.3f} | EVIDENCE={snippet}"
                )
            blocks.append("")
        if self.chart:
            blocks.append("CHART DATA (from verified structured facts only):")
            blocks.append(str(self.chart.get("data")))
            blocks.append("")
        if not self.structured and not self.rag and not self.conflicts and not self.multi_fact:
            blocks.append("NO RELIABLE EVIDENCE FOUND.")
        return "\n".join(blocks)

    def payload(self) -> dict[str, Any]:
        return {
            "structured_evidence": [structured_to_dict(h) for h in self.structured],
            "rag_evidence": [rag_to_dict(h) for h in self.rag],
            "conflicts": [conflict_to_dict(c) for c in self.conflicts],
            "chart": self.chart,
            "warnings": list(self.warnings),
            "multi_fact": self.multi_fact,
            "llm_meta": self.llm_meta,
        }
