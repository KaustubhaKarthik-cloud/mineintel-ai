"""Semantic retriever over indexed document chunks."""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.embeddings.provider import EmbeddingProvider, get_embedding_provider
from app.retrieval.vector_store import SearchHit, search_similar

_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "in",
    "on",
    "for",
    "to",
    "was",
    "were",
    "is",
    "are",
    "did",
    "do",
    "does",
    "how",
    "much",
    "what",
    "which",
    "when",
    "year",
    "from",
    "with",
    "by",
}

_ENTITIES = (
    "nlcil",
    "neyveli",
    "lignite",
    "sccl",
    "singareni",
    "bailadila",
    "ntpl",
)

# Competing company names — demote when query targets a different entity
_ORG_ALIASES = {
    "nlcil": ("nlcil", "nlc india", "neyveli"),
    "sccl": ("sccl", "singareni"),
    "ntpl": ("ntpl",),
    "bailadila": ("bailadila",),
}


def _query_terms(query: str) -> set[str]:
    raw = re.findall(r"[a-z0-9][a-z0-9.\-]{1,}", (query or "").lower())
    terms: set[str] = set()
    for t in raw:
        if t in _STOP or len(t) < 2:
            continue
        terms.add(t)
        m = re.fullmatch(r"(20\d{2})-20(\d{2})", t)
        if m:
            terms.add(f"{m.group(1)}-{m.group(2)}")
        m2 = re.fullmatch(r"(20\d{2})-(\d{2})", t)
        if m2:
            terms.add(f"{m2.group(1)}-20{m2.group(2)}")
    if "produced" in terms:
        terms.add("production")
    if "production" in terms:
        terms.add("produced")
    # Do NOT map coal ↔ lignite — they are distinct metrics.
    return terms


def _detected_orgs(text: str) -> set[str]:
    hay = text.lower()
    found: set[str] = set()
    for key, aliases in _ORG_ALIASES.items():
        if any(a in hay for a in aliases):
            found.add(key)
    return found


def _keyword_boost(query: str, text: str) -> float:
    """Boost chunks that match query entities and production facts.

    Ranking cues are linguistic/structural — not a hard-coded org→answer map.
    Entity tokens from the query must appear in the chunk to earn production-table boosts.
    """
    terms = _query_terms(query)
    if not terms or not text:
        return 0.0
    hay = text.lower()
    hits = sum(1 for t in terms if t in hay)
    if hits == 0 and not any(e in hay for e in _ENTITIES):
        return -0.05

    ratio = hits / max(len(terms), 1)
    bonus = 0.35 * ratio

    for ent in _ENTITIES:
        if ent in terms and ent in hay:
            bonus += 0.12

    # Soft entity tokens: any multi-char query term that looks like a proper noun / place
    # Prefer chunks that literally contain the queried entity words.
    # Extract candidate entity-like tokens (not stop/metric)
    metricish = {"production", "produced", "produce", "coal", "lignite", "overburden", "output", "tonnage", "fy24", "fy25"}
    entity_like = [t for t in terms if t not in metricish and t not in _STOP and not t.startswith("fy") and len(t) >= 3]
    if entity_like:
        if any(t in hay for t in entity_like):
            bonus += 0.28
        else:
            # Strong penalty when the query names an entity absent from the chunk
            bonus -= 0.45

    production_ask = bool(
        terms & {"production", "produced", "overburden", "lignite", "coal", "output", "tonnage"}
    )
    entity_present = (not entity_like) or any(t in hay for t in entity_like)
    # Prefer reconstructed / labeled production tables ONLY when entity also matches
    if (production_ask or "performance" in terms) and entity_present:
        if "production performance" in hay:
            bonus += 0.18
        if "reconstructed from source table" in hay:
            bonus += 0.20
        if re.search(r"(coal|lignite|overburden):\s*target\s+\d", hay):
            bonus += 0.12
    elif production_ask and not entity_present:
        # Demote generic production tables that ignore the asked entity
        if "reconstructed from source table" in hay or "production performance" in hay:
            bonus -= 0.25

    if production_ask:
        if "authorised capital" in hay or "paid up equity" in hay:
            bonus -= 0.15
        if "joint venture" in hay and "production performance" not in hay and "reconstructed" not in hay:
            bonus -= 0.10

    q_orgs = _detected_orgs(query)
    c_orgs = _detected_orgs(hay)
    if q_orgs and c_orgs and q_orgs.isdisjoint(c_orgs):
        bonus -= 0.22

    return max(-0.55, min(0.75, bonus))

def retrieve(
    db: Session,
    query: str,
    *,
    top_k: Optional[int] = None,
    min_score: Optional[float] = None,
    document_id: Optional[str] = None,
    provider: Optional[EmbeddingProvider] = None,
) -> list[SearchHit]:
    settings = get_settings()
    k = top_k if top_k is not None else settings.search_top_k
    threshold = min_score if min_score is not None else settings.min_similarity_threshold
    emb_provider = provider or get_embedding_provider()
    qvec = emb_provider.embed_text(query)
    pool = search_similar(
        db,
        qvec,
        top_k=max(50, k * 10),
        min_score=0.0,
        document_id=document_id,
    )
    hybrid: list[SearchHit] = []
    for hit in pool:
        boosted = min(1.0, max(0.0, hit.score + _keyword_boost(query, hit.chunk.content or "")))
        if boosted >= threshold:
            hybrid.append(SearchHit(chunk=hit.chunk, score=boosted))
    hybrid.sort(key=lambda h: h.score, reverse=True)
    return hybrid[: max(1, min(k, 50))]
