"""Rule/config-based document domain classification from extracted text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.geology.taxonomy import DOMAIN_CUES, DOMAIN_LABELS, DocumentDomain


@dataclass
class ClassificationResult:
    domain: str
    label: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    matched_terms: dict[str, list[str]] = field(default_factory=dict)
    method: str = "keyword_weighted"
    text_chars_used: int = 0


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def classify_document_text(
    text: str,
    *,
    filename_hint: Optional[str] = None,
) -> ClassificationResult:
    """Classify using page/body text. Filename is a weak optional hint only."""
    body = _normalize_text(text)
    # Cap work on huge OCR dumps
    body_use = body[:80_000]
    scores: dict[str, float] = {d.value: 0.0 for d in DocumentDomain if d != DocumentDomain.OTHER}
    matched: dict[str, list[str]] = {k: [] for k in scores}

    for domain, cues in DOMAIN_CUES.items():
        for phrase, weight in cues:
            # Word-ish boundary for short tokens; phrase search for multi-word
            if " " in phrase:
                count = body_use.count(phrase)
            else:
                count = len(re.findall(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", body_use))
            if count:
                scores[domain] += weight * min(count, 8)
                if phrase not in matched[domain]:
                    matched[domain].append(phrase)

    # Weak filename hint (never sole decision for GEOLOGICAL)
    name = _normalize_text(filename_hint or "")
    if name:
        for domain, cues in DOMAIN_CUES.items():
            for phrase, weight in cues[:6]:
                if phrase in name:
                    scores[domain] += weight * 0.35

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_domain, best_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    total = sum(scores.values())

    if best_score < 2.5 or total < 3.0:
        domain = DocumentDomain.OTHER.value
        confidence = 0.35 if best_score > 0 else 0.2
    else:
        domain = best_domain
        # Confidence from score mass + separation from runner-up
        mass = best_score / max(total, 1e-6)
        separation = (best_score - second) / max(best_score, 1e-6)
        confidence = round(min(0.97, 0.45 + 0.35 * mass + 0.25 * separation), 3)

    return ClassificationResult(
        domain=domain,
        label=DOMAIN_LABELS.get(domain, DOMAIN_LABELS[DocumentDomain.OTHER.value]),
        confidence=confidence,
        scores={k: round(v, 3) for k, v in scores.items()},
        matched_terms={k: v for k, v in matched.items() if v},
        text_chars_used=len(body_use),
    )
