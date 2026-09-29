"""Display helpers for Indian mining geography labels (presentation only).

Does not invent coordinates. Keeps source evidence intact.
"""

from __future__ import annotations

import re
from typing import Optional

# Korea district (Chhattisgarh) appears in GSI/CMPDI-style headers as
# "DISTRICT : KOREA, CHHATTISGARH" — not the country of South Korea.
_KOREA_DISTRICT_RE = re.compile(
    r"(?i)\b(?:district\s*[:\-]?\s*)?korea\s*[,/]?\s*chhattisgarh\b"
)
_KOREA_BARE_DISTRICT_RE = re.compile(
    r"(?i)\bdistrict\s*[:\-]?\s*korea\b(?!\s*,?\s*republic|\s*,?\s*south)"
)


def format_location_display(text: Optional[str]) -> Optional[str]:
    """Return a disambiguated location label when evidence names Korea district."""
    if not text:
        return None
    if _KOREA_DISTRICT_RE.search(text) or _KOREA_BARE_DISTRICT_RE.search(text):
        return "Korea District, Chhattisgarh, India"
    return None


def annotate_evidence_display(evidence: Optional[str]) -> Optional[str]:
    """Leave evidence text unchanged; optionally prefix a clear location note."""
    if not evidence:
        return evidence
    label = format_location_display(evidence)
    if not label:
        return evidence
    # Avoid double-prefixing
    if evidence.strip().startswith(label):
        return evidence
    return f"[{label}]\n{evidence}"
