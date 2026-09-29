"""Geological entity extraction + safe matching (G2).

No document-specific names. Seam I must not match Seam II / III / VIA.
"""

from __future__ import annotations

import re
from typing import Optional

from app.geology.seam_ids import (
    SEAM_CODE_BEFORE_RE,
    SEAM_QUALIFIED_RE,
    is_valid_seam_identifier,
    normalize_seam_identifier,
    strip_seam_prefix,
)

_BH_IN_QUERY_RE = re.compile(
    r"(?i)\b(?:bore\s*hole|borehole|drill\s*hole|dh)\s*(?:no\.?|number|#|:)?\s*"
    r"([A-Z]{0,6}[-_]?\d{1,5}[A-Z0-9]*)\b"
    r"|\b((?:BH|CMBJ|CMNPB|SKJ|MPRJ|NPB)[-_]?\w{1,12})\b"
)

_FORMATION_IN_QUERY_RE = re.compile(
    r"(?i)\b(?!(?:the|a|an|and|or|of|to|for|in|on|at|by|from|with|this|that|"
    r"through|into|what|which|where|when|who|how|overlies|underlies|overlie|underlie)\b)"
    r"((?:Upper|Lower|Middle)\s+)?"
    r"([A-Za-z][A-Za-z]{2,}(?:\s+[A-Za-z][A-Za-z]{2,})?)\s+Formations?\b"
    r"|\bformation\s+(?:of\s+)?(?:the\s+)?"
    r"(?!(?:the|a|an|and|or|what|which)\b)([A-Za-z][A-Za-z]{2,}(?:\s+[A-Za-z][A-Za-z]{2,})?)\b"
)

# Words that never form a geological formation proper name (generic, not doc-specific).
_FORMATION_NAME_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "or",
        "the",
        "this",
        "that",
        "these",
        "those",
        "its",
        "their",
        "our",
        "of",
        "to",
        "for",
        "in",
        "on",
        "at",
        "by",
        "from",
        "with",
        "into",
        "onto",
        "over",
        "under",
        "above",
        "below",
        "through",
        "across",
        "between",
        "among",
        "along",
        "via",
        "per",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "may",
        "might",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "not",
        "no",
        "only",
        "also",
        "such",
        "same",
        "other",
        "another",
        "each",
        "every",
        "both",
        "all",
        "any",
        "some",
        "more",
        "most",
        "few",
        "several",
        "various",
        "respective",
        "entire",
        "whole",
        "upper",
        "lower",
        "middle",
        "main",
        "local",
        "regional",
        "general",
        "typical",
        "said",
        "following",
        "preceding",
        "concerned",
        "present",
        "given",
        "mentioned",
        "described",
        "interpreted",
        "identified",
        "established",
        "reported",
        "observed",
        "studied",
        "mapped",
        "geological",
        "geology",
        "stratigraphic",
        "stratigraphy",
        "sedimentary",
        "lithology",
        "lithologic",
        "lithological",
        "guide",
        "guides",
        "coaly",
        "carbonaceous",
        "separate",
        "associated",
        "underlying",
        "overlying",
        "intervening",
        "host",
        "parent",
        "source",
        "target",
        "subject",
        "corresponding",
        "equivalent",
        "probable",
        "possible",
        "potential",
        "major",
        "minor",
        "thick",
        "thin",
        "hard",
        "soft",
        "new",
        "old",
        "first",
        "second",
        "third",
        "what",
        "which",
        "where",
        "when",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "overlies",
        "underlies",
        "overlie",
        "underlie",
        "overlying",
        "underlying",
        "comprises",
        "comprise",
        "consists",
        "consist",
        "includes",
        "include",
        "including",
        "forms",
        "form",
        "forming",
        "occurs",
        "occur",
        "occurring",
        "belongs",
        "belong",
        "belonging",
        "hosts",
        "host",
        "hosting",
        "contains",
        "contain",
        "containing",
        "formation",
        "formations",
        "member",
        "group",
        "horizon",
        "seam",
        "seams",
        "borehole",
        "boreholes",
        "shale",
        "sandstone",
        "siltstone",
        "claystone",
        "mudstone",
        "limestone",
        "ironstone",
        "coal",
        "rock",
        "rocks",
        "bed",
        "beds",
        "unit",
        "units",
        "sequence",
        "sequences",
        "section",
        "sections",
        "part",
        "parts",
        "type",
        "types",
        "nature",
        "character",
        "presence",
        "absence",
        "occurrence",
        "occurrences",
        "boundary",
        "boundaries",
        "contact",
        "contacts",
        "thickness",
        "depth",
        "information",
        "description",
        "chapter",
        "table",
        "figure",
        "page",
        "etc",
        "block",
        "area",
        "zone",
        "region",
    }
)

# Strong nearby cues that support treating a proper name + Formation as geological.
_FORMATION_CONTEXT_CUES = re.compile(
    r"(?i)\b(?:"
    r"coal\s+seam|stratigraph(?:y|ic)|geological\s+map|litholog(?:y|ical)|"
    r"formation\s+boundar|basin|coalfield|sedimentary|member|group|"
    r"horizon|strata|outcrop|subcrop|borehole|drill(?:ing|ed)|"
    r"gondwana|permian|carboniferous|triassic|cretaceous|jurassic|"
    r"geological\s+formation|of\s+the\s+\w+\s+formation|"
    r"belong(?:s|ing)?\s+to|overlain|underlain|conformit|unconformit"
    r")\b"
)


def seam_match_key(name: Optional[str]) -> str:
    """Canonical key for equality — never substring-match roman numerals."""
    if not name:
        return ""
    norm = normalize_seam_identifier(name)
    rest = strip_seam_prefix(norm or name).lower()
    rest = re.sub(r"\s+", " ", rest).strip()
    return rest


def seams_match(a: Optional[str], b: Optional[str]) -> bool:
    ka, kb = seam_match_key(a), seam_match_key(b)
    if not ka or not kb:
        return False
    return ka == kb


def borehole_match_key(name: Optional[str]) -> str:
    if not name:
        return ""
    return re.sub(r"[-_\s]", "", (name or "").lower())


def boreholes_match(a: Optional[str], b: Optional[str]) -> bool:
    ka, kb = borehole_match_key(a), borehole_match_key(b)
    return bool(ka and kb and ka == kb)


def formation_match_key(name: Optional[str]) -> str:
    if not name:
        return ""
    s = re.sub(r"(?i)\bformation\b", "", name)
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def formations_match(a: Optional[str], b: Optional[str]) -> bool:
    ka, kb = formation_match_key(a), formation_match_key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka in kb or kb in ka


def _strip_formation_leading_noise(raw: str) -> str:
    """Drop leading determiners/conjunctions/verbs accidentally captured before a proper name."""
    s = re.sub(r"\s+", " ", (raw or "")).strip(" .,;:|-")
    leading = {
        "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "at", "by",
        "from", "with", "into", "this", "that", "these", "those", "its", "their",
        "as", "via", "per", "through", "across", "between", "among", "along",
        "what", "which", "where", "when", "who", "how",
        "overlies", "underlies", "overlie", "underlie", "overlying", "underlying",
        "comprises", "comprise", "consists", "consist", "includes", "include",
        "including", "forms", "form", "forming", "occurs", "occur", "occurring",
        "belongs", "belong", "belonging", "hosts", "host", "hosting",
        "contains", "contain", "containing", "presents", "present",
        "shows", "show", "showing", "represents", "represent",
    }
    parts = s.split()
    while parts and parts[0].lower().strip(".,;:") in leading:
        parts = parts[1:]
    return " ".join(parts)


def normalize_formation_name(raw: Optional[str]) -> Optional[str]:
    """Normalize to '<Proper Name> Formation' without changing meaning."""
    if not raw:
        return None
    s = _strip_formation_leading_noise(str(raw))
    s = re.sub(r"(?i)\bformations?\b", "", s).strip(" .,;:|-")
    if not s:
        return None
    parts = [p for p in s.split() if p]
    if not parts:
        return None
    titled = " ".join(
        p.upper() if re.fullmatch(r"[IVXLC]+", p, re.I) else p[:1].upper() + p[1:].lower()
        for p in parts
    )
    return f"{titled} Formation"


def is_plausible_formation_name(
    raw: Optional[str],
    *,
    context: Optional[str] = None,
) -> bool:
    """True when text looks like a named geological formation, not a grammar fragment."""
    if not raw:
        return False
    raw_s = re.sub(r"\s+", " ", str(raw)).strip(" .,;:|-")
    # Reject clear non-name patterns before stripping (descriptive / grammar)
    if re.search(
        r"(?i)^(?:through|lithology|guide|coaly|separate|carbonaceous|geological|"
        r"interpreted|characteristics?|the|this|that|above|below|formation)\b",
        raw_s,
    ) and not re.search(
        r"(?i)\b(?:[A-Z][a-z]{3,})\s+Formation\b",
        raw_s,
    ):
        # Allow "X Formation" proper names; reject "guide to Formation" / "coaly Formation"
        if re.search(
            r"(?i)\b(?:through\s+the|lithology\s+of|guide\s+to|coaly|separate\s+carbonaceous|"
            r"formation\s+characteristics|carbonaceous\s+formations?)\b",
            raw_s,
        ) or re.search(
            r"(?i)^(?:coaly|carbonaceous|geological|interpreted|separate)\s+formations?\b",
            raw_s,
        ):
            return False
    if re.search(
        r"(?i)\bformation\s+characteristics\b|\bguide\s+to\s+formation\b|"
        r"\bthrough\s+the\s+formation\b|\blithology\s+of\s+formation\b|"
        r"\bcoaly\s+formation\b|\bseparate\s+carbonaceous\s+formation\b|"
        r"\bcarbonaceous\s+formations?\b",
        raw_s,
    ):
        return False
    # Context: descriptive "formation characteristics" / "qualitative guide"
    if context and re.search(
        r"(?i)\b(?:guide\s+to\s+formation|formation\s+characteristics|"
        r"carbonaceous\s+formations?|through\s+the\s+formation|"
        r"lithology\s+of\s+formation)\b",
        context,
    ):
        # Still allow a distinct proper name in the same window (e.g. Raniganj Formation)
        if not re.search(
            r"(?i)\b(?!(?:the|a|an|and|or|of|to|for|coaly|carbonaceous|geological|guide|"
            r"lithology|through|separate)\b)([A-Z][a-z]{3,})\s+Formations?\b",
            context,
        ):
            return False
    s = _strip_formation_leading_noise(raw_s)
    s = re.sub(r"(?i)\bformations?\s*$", "", s).strip(" .,;:|-")
    if not s:
        return False
    tokens = [t for t in re.findall(r"[A-Za-z]+", s) if t]
    if not tokens or len(tokens) > 3:
        return False
    low_tokens = [t.lower() for t in tokens]
    # Grammar / non-name tokens always disqualify the candidate
    grammar_block = {
        "a", "an", "and", "or", "the", "this", "that", "these", "those",
        "its", "their", "our", "of", "to", "for", "in", "on", "at", "by",
        "from", "with", "into", "onto", "over", "under", "above", "below",
        "through", "across", "between", "among", "along", "via", "per",
        "as", "is", "are", "was", "were", "be", "been", "being",
        "has", "have", "had", "do", "does", "did",
        "what", "which", "where", "when", "who", "whom", "whose", "why", "how",
        "not", "no", "only", "also", "such", "same", "other", "another",
        "each", "every", "both", "all", "any", "some", "more", "most",
        "few", "several", "various", "said", "etc",
    }
    if any(t in grammar_block for t in low_tokens):
        return False
    # Descriptive / non-proper content words (alone or dominating) are not formation names
    content_block = _FORMATION_NAME_STOPWORDS - grammar_block - {
        "upper", "lower", "middle",  # allowed as qualifiers with a proper name
    }
    content_hits = [t for t in low_tokens if t in content_block]
    proper_tokens = [t for t in low_tokens if t not in content_block and t not in grammar_block]
    if not proper_tokens:
        return False
    if content_hits and not any(len(t) >= 4 for t in proper_tokens):
        return False
    # Require at least one token that looks like a proper name
    properish = [
        t
        for t in tokens
        if t.lower() in proper_tokens
        and (
            (t[:1].isupper() and (len(t) == 1 or t[1:].islower() or t.isupper()))
            or t.isupper()
            or (len(t) >= 4 and t.lower() not in content_block)
        )
    ]
    if not properish:
        return False
    # Single very short token (≤2 letters) is not a formation name
    if len(proper_tokens) == 1 and len(proper_tokens[0]) <= 2:
        return False
    # Optional context gate for weak capitalization
    if context:
        window = context.strip()
        if not _FORMATION_CONTEXT_CUES.search(window):
            if not any(len(t) >= 4 and t[:1].isupper() for t in tokens if t.lower() in proper_tokens):
                return False
    return True


def extract_formation_from_question(question: str) -> Optional[str]:
    m = _FORMATION_IN_QUERY_RE.search(question or "")
    if not m:
        return None
    # groups: 1=optional Upper/Lower, 2=name, 3=alt name after "formation of"
    prefix = (m.group(1) or "").strip()
    name = (m.group(2) or m.group(3) or "").strip()
    if prefix:
        name = f"{prefix} {name}".strip()
    if not is_plausible_formation_name(name, context=question):
        return None
    return normalize_formation_name(name)


def extract_formations_from_text(
    text: str,
    *,
    require_context: bool = False,
) -> list[str]:
    """Extract unique plausible formation names from document/RAG text."""
    found: list[str] = []
    seen: set[str] = set()
    for m in _FORMATION_IN_QUERY_RE.finditer(text or ""):
        prefix = (m.group(1) or "").strip()
        raw = (m.group(2) or m.group(3) or "").strip()
        if prefix:
            raw = f"{prefix} {raw}".strip()
        a = max(0, m.start() - 80)
        b = min(len(text or ""), m.end() + 40)
        window = (text or "")[a:b]
        if require_context and not _FORMATION_CONTEXT_CUES.search(window):
            toks = re.findall(r"[A-Za-z]+", raw)
            if not (toks and all(len(t) >= 4 and t[:1].isupper() for t in toks)):
                continue
        if not is_plausible_formation_name(raw, context=window):
            continue
        norm = normalize_formation_name(raw)
        if not norm:
            continue
        key = formation_match_key(norm)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(norm)
    return found


def extract_seam_from_question(question: str) -> Optional[str]:
    q = question or ""
    for m in SEAM_QUALIFIED_RE.finditer(q):
        label = normalize_seam_identifier(m.group(1))
        if label:
            return label
    for m in SEAM_CODE_BEFORE_RE.finditer(q):
        label = normalize_seam_identifier(m.group(1))
        if label:
            return label
    return None


def extract_seams_from_question(question: str) -> list[str]:
    q = question or ""
    found: list[str] = []
    for m in list(SEAM_QUALIFIED_RE.finditer(q)) + list(SEAM_CODE_BEFORE_RE.finditer(q)):
        label = normalize_seam_identifier(m.group(1))
        if label and label not in found:
            found.append(label)
    return found


def extract_borehole_from_question(question: str) -> Optional[str]:
    m = _BH_IN_QUERY_RE.search(question or "")
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    return (raw or "").strip().upper() or None


def is_listing_intent(question: str, metrics: list[str]) -> bool:
    q = (question or "").lower()
    if not re.search(r"\b(?:what|which|list|identify|identified|mentioned|reported|present)\b", q):
        return False
    # Resource / reserve / thickness / depth asks are factual, not entity listings
    if metrics and metrics[0] in {
        "resource",
        "reserve",
        "resource_quantity",
        "reserve_quantity",
        "seam_thickness",
        "formation_thickness",
        "minimum_workable_seam_thickness",
        "seam_parting_thickness",
        "overburden_thickness",
        "seam_depth",
        "borehole_depth",
        "coal_quality",
    }:
        return False
    if re.search(
        r"\b(?:resource|resources|reserve|reserves|inferred|indicated|measured)\b",
        q,
    ) and re.search(r"\b(?:for|of|in)\b", q):
        # "resource for Seam R4" is factual even if "seam" also appears
        if not re.search(
            r"\b(?:what|which)\s+(?:coal\s+)?(?:seams?|boreholes?|formations?|litholog(?:y|ies))\b",
            q,
        ):
            return False
    listing_metrics = {"seam", "borehole", "lithology", "formation", "geological_structure"}
    if metrics and metrics[0] in listing_metrics:
        return True
    return bool(re.search(r"\b(?:seams?|boreholes?|formations?|lithology)\b", q)) and not re.search(
        r"\b(?:thickness|depth|how\s+thick|how\s+deep|resource|reserve)\b", q
    )


def infer_metric_kind_from_fields(
    *,
    metric_kind: Optional[str] = None,
    seam_name: Optional[str] = None,
    borehole_id: Optional[str] = None,
    geological_formation: Optional[str] = None,
    lithology: Optional[str] = None,
    geological_structure: Optional[str] = None,
    coal_quality_parameter: Optional[str] = None,
    has_thickness: bool = False,
    has_depth: bool = False,
    evidence_text: Optional[str] = None,
) -> Optional[str]:
    """Assign canonical metric_kind for structured storage (G2)."""
    if metric_kind:
        return metric_kind
    ev = (evidence_text or "").lower()
    if coal_quality_parameter:
        return "coal_quality"
    if re.search(r"(?i)\b(?:minimum\s+)?workable\s+thickness\b", ev):
        return "minimum_workable_seam_thickness"
    if re.search(
        r"(?i)\b(?:inferred|indicated|measured|gross)\s+(?:coal\s+)?resources?\b"
        r"|\bresources?\b.+\b(?:MT|million\s*tonnes?)\b"
        r"|\b(?:MT|million\s*tonnes?)\b.+\bresources?\b",
        ev,
    ) and re.search(r"\d+\.\d+", ev):
        if re.search(r"(?i)\breserves?\b", ev) and not re.search(r"(?i)\bresources?\b", ev):
            return "reserve"
        return "resource"
    if re.search(
        r"(?i)\b(?:inferred|indicated|measured|proved|probable)\s+(?:coal\s+)?reserves?\b",
        ev,
    ) and re.search(r"\d+\.\d+", ev):
        return "reserve"
    if "parting" in ev and has_thickness:
        return "seam_parting_thickness"
    if "overburden" in ev and has_thickness:
        return "overburden_thickness"
    if has_thickness and seam_name and is_valid_seam_identifier(seam_name):
        return "seam_thickness"
    if has_thickness and geological_formation and not seam_name:
        return "formation_thickness"
    if has_depth and borehole_id:
        return "borehole_depth"
    if has_depth and seam_name:
        return "seam_depth"
    if has_depth:
        return "stratigraphic_depth"
    if seam_name and is_valid_seam_identifier(seam_name):
        return "seam"
    if borehole_id:
        return "borehole"
    if lithology:
        return "lithology"
    if geological_formation:
        return "formation"
    if geological_structure:
        return "geological_structure"
    return None


def detect_value_qualifier(text: Optional[str]) -> Optional[str]:
    t = text or ""
    if re.search(r"(?i)\b(?:from|between|to|[-–—])\b", t) and re.search(r"\d", t):
        if re.search(r"\d.+\d", t):
            return "range"
    if re.search(r"(?i)^\s*[>~≈]|approximately|about\s+\d|~\s*\d", t):
        return "~"
    if re.search(r"(?i)(?:greater\s+than|>\s*\d|more\s+than)", t):
        return ">"
    if re.search(r"(?i)(?:less\s+than|<\s*\d|below\s+\d)", t):
        return "<"
    return None
