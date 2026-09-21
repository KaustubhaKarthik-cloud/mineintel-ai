"""Geological seam identifier recognition (generic; no document-specific names).

A phrase containing the word \"seam\" is not automatically a seam identifier.
Valid identifiers look like: R4, Seam IV, III Top, VIA, VIA Bottom, etc.
"""

from __future__ import annotations

import re
from typing import Optional

# English / narrative leftovers that appear after "seam …" in OCR prose.
SEAM_IDENTIFIER_NOISE = frozenset(
    {
        "thickness",
        "depth",
        "quality",
        "section",
        "sections",
        "has",
        "name",
        "names",
        "seam",
        "seams",
        "coal",
        "and",
        "are",
        "the",
        "of",
        "to",
        "for",
        "with",
        "from",
        "varies",
        "varying",
        "general",
        "workable",
        "developed",
        "encountered",
        "present",
        "absent",
        "parameters",
        "parameter",
        "folio",
        "correlation",
        "structure",
        "stratum",
        "overall",
        "predominant",
        "min",
        "max",
        "no",
        "is",
        "was",
        "were",
        "been",
        "being",
        "as",
        "at",
        "by",
        "on",
        "or",
        "an",
        "be",
        "it",
        "if",
        "so",
        "up",
        "but",
        "can",
        "in",
        "s",
        "found",
        "only",
        "wise",
        "dirt",
        "band",
        "bands",
        "horizon",
        "horizons",
        "description",
        "described",
        "details",
        "detail",
        "against",
        "log",
        "logs",
        "geophysical",
        "interpretation",
        "investigated",
        "investigation",
        "uncorrelated",
        "correlated",
        "formation",
        "formations",
        "sandstone",
        "shale",
        "carbonaceous",
        "parting",
        "partings",
        "roof",
        "floor",
        "incrop",
        "split",
        "determined",
        "generated",
        "gradually",
        "hence",
        "couldn",
        "does",
        "got",
        "missing",
        "also",
        "this",
        "that",
        "these",
        "those",
        "which",
        "where",
        "when",
        "while",
        "during",
        "after",
        "before",
        "above",
        "below",
        "between",
        "within",
        "block",
        "area",
        "zone",
        "occur",
        "occurs",
        "occurrence",
        "occurrences",
        "identified",
        "mentioned",
        "reported",
        "shown",
        "given",
        "taken",
        "considered",
        "corresponding",
        "respectively",
        "namely",
        "viz",
        "etc",
    }
)

# Core identifier body (no leading "Seam"):
#   IV | III Top | VIA | VIA Bottom | R4 | L1 | 4A
_SEAM_ID_BODY = (
    r"(?:"
    r"[IVXLC]{1,6}(?:[AB])?(?:\s+(?:Top|Bottom|T|B))?"
    r"|[A-Za-z]{1,3}\d+[A-Za-z]?"
    r"|\d{1,3}[A-Za-z]?"
    r")"
)

# "Seam R4" / "Seam III Top" / "seam VIA"
SEAM_QUALIFIED_RE = re.compile(
    rf"(?i)\bseam\s+(?:section\s+)?({_SEAM_ID_BODY})\b"
)

# "thickness of the seam IV"
SEAM_OF_THICKNESS_RE = re.compile(
    rf"(?i)\bthickness\s+of\s+(?:the\s+)?(?:seam\s+(?:section\s+)?)?({_SEAM_ID_BODY})\b"
)

# "R4 seam" / "III Top seam" (identifier before the word seam).
# Bare digits are excluded: "2 seams found" must not become Seam 2.
_SEAM_ID_BODY_BEFORE = (
    r"(?:"
    r"[IVXLC]{1,6}(?:[AB])?(?:\s+(?:Top|Bottom|T|B))?"
    r"|[A-Za-z]{1,3}\d+[A-Za-z]?"
    r")"
)
SEAM_CODE_BEFORE_RE = re.compile(
    rf"(?i)\b({_SEAM_ID_BODY_BEFORE})\s+seams?\b"
)

_SEAM_ID_BODY_FULL = re.compile(rf"(?i)^({_SEAM_ID_BODY})$")

# Source-grounded unnamed / uncorrelated coal-seam mentions (no invented identifier).
UNCORRELATED_SEAM_RE = re.compile(
    r"(?i)\b(?:an?\s+|one\s+|the\s+)?"
    r"(?:uncorrelated|unnamed|un-?named|unidentified)\s+"
    r"(?:coal\s+)?seams?\b"
    r"(?:\s+of\s+(?:the\s+)?([A-Za-z][A-Za-z\s-]{1,40}?)\s+Formation)?"
)

# "a coal seam of Barakar Formation" when nearby context says uncorrelated / left uncorrelated
COAL_SEAM_OF_FORMATION_RE = re.compile(
    r"(?i)\b(?:an?\s+|one\s+|the\s+)?"
    r"(?:coal\s+)?seam\s+of\s+(?:the\s+)?"
    r"([A-Za-z][A-Za-z\s-]{1,40}?)\s+Formation\b"
)

DISPLAY_UNCORRELATED = "Uncorrelated coal seam"
DISPLAY_UNNAMED = "Unnamed coal seam"


def strip_seam_prefix(name: str) -> str:
    return re.sub(r"(?i)^seam\s+", "", (name or "").strip()).strip()


def is_valid_seam_identifier(raw: Optional[str]) -> bool:
    """True when raw is a geological seam identifier, not narrative text."""
    if not raw:
        return False
    rest = strip_seam_prefix(raw)
    if not rest or len(rest) > 24:
        return False
    low = rest.lower().strip(" .:,;")
    if low in SEAM_IDENTIFIER_NOISE or low == "seam":
        return False
    # Reject formation-like multi-word English (e.g. "Barakar Formation")
    if re.search(r"(?i)\bformation\b", rest):
        return False
    if not _SEAM_ID_BODY_FULL.match(rest):
        return False
    # Extra guard: pure alphabetic tokens must be roman (+ optional A/B / Top|Bottom)
    if rest.isalpha() or re.fullmatch(r"(?i)[a-z]+\s+(?:top|bottom)", rest):
        if not re.fullmatch(
            r"(?i)[ivxlc]{1,6}(?:[ab])?(?:\s+(?:top|bottom))?",
            rest,
        ):
            return False
    return True


def normalize_seam_identifier(raw: Optional[str]) -> Optional[str]:
    """Canonicalize an explicit seam identifier; return None if invalid."""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", strip_seam_prefix(raw)).strip()
    # Allow "R4 seam" / "III Top seam" as input forms
    s = re.sub(r"(?i)\s+seams?$", "", s).strip()
    if not s or not is_valid_seam_identifier(s):
        return None
    m = re.fullmatch(
        r"(?i)([ivxlc]{1,6})([ab])?(?:\s+(top|bottom|t|b))?",
        s,
    )
    if m:
        core = m.group(1).upper()
        letter = (m.group(2) or "").upper()
        qual = m.group(3)
        label = f"Seam {core}{letter}"
        if qual:
            q = qual.lower()
            if q in {"t", "top"}:
                label += " Top"
            elif q in {"b", "bottom"}:
                label += " Bottom"
        return label
    m2 = re.fullmatch(r"(?i)([a-z]{1,3})(\d+)([a-z]?)", s)
    if m2:
        return f"Seam {m2.group(1).upper()}{m2.group(2)}{(m2.group(3) or '').upper()}"
    m3 = re.fullmatch(r"(?i)(\d{1,3})([a-z]?)", s)
    if m3:
        return f"Seam {m3.group(1)}{(m3.group(2) or '').upper()}"
    # Fallback: title-case conserved identifier
    return f"Seam {s.upper() if len(s) <= 6 else s}"


def seam_display_label(
    *,
    seam_name: Optional[str] = None,
    seam_status: Optional[str] = None,
) -> Optional[str]:
    """Human-facing label. Never invents an identifier for uncorrelated/unnamed seams."""
    status = (seam_status or "").lower().strip()
    if status == "uncorrelated":
        return DISPLAY_UNCORRELATED
    if status == "unnamed":
        return DISPLAY_UNNAMED
    if seam_name and is_valid_seam_identifier(seam_name):
        return normalize_seam_identifier(seam_name) or seam_name
    return None


def is_named_seam_entity(
    *,
    seam_name: Optional[str] = None,
    seam_status: Optional[str] = None,
) -> bool:
    status = (seam_status or "named").lower()
    if status in {"uncorrelated", "unnamed"}:
        return False
    return bool(seam_name and is_valid_seam_identifier(seam_name))
