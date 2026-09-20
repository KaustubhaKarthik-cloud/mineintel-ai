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

    def to_prompt_context(self) -> str:
        blocks = [f"QUESTION: {self.plan.raw_question}", f"QUERY_TYPE: {self.plan.query_type}", ""]
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
        if self.structured:
            blocks.append("VERIFIED STRUCTURED EVIDENCE:")
            for h in self.structured:
                blocks.append(
                    f"- {h.entity} | {h.metric} | {h.period} = {h.value} {h.unit or ''} "
                    f"(status={h.status}) source={h.document_name} page={h.page} "
                    f"evidence={h.evidence_text or ''}"
                )
            blocks.append("")
        if self.rag:
            blocks.append("DOCUMENT / RAG EVIDENCE:")
            for i, h in enumerate(self.rag, 1):
                loc = h.sheet_name or (f"page {h.page}" if h.page is not None else "n/a")
                blocks.append(
                    f"- [R{i}] {h.document_name} ({loc}) score={h.score:.3f}: {h.text[:500]}"
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
        }
