"""Evidence-aware query parsing and routing (Phase 6).

Routing is two-stage:
1) parse_query — extract entity/metric/period intent from language (no DB).
2) resolve_route — choose structured/rag/hybrid based on what evidence
   CURRENTLY exists in the structured DB and (when needed) the vector index.

Does not hard-code specific questions, documents, page numbers, or values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

# Linguistic metric cues — field detection, not org→route maps.
METRIC_CUES: dict[str, tuple[str, ...]] = {
    "production_target": ("production target", "target production", "annual target"),
    "achievement_percentage": ("achievement", "achievement percentage", "percent achievement"),
    "overburden": ("overburden", "ob removal", "over burden"),
    "lignite": ("lignite",),
    "coal": ("coal production", "coal"),
    "dispatch": ("dispatch",),
    "grade": ("ore grade", "grade"),
    "reserves": ("reserves",),
    "resources": ("resources",),
    "production": ("production", "produced", "output", "tonnage", "figures"),
}

# Geological phrases take priority over bare mining "coal" / production cues.
GEOLOGICAL_PHRASE_CUES: tuple[str, ...] = (
    "coal seam horizon",
    "coal seam horizons",
    "coal seams",
    "coal seam",
    "seam thickness",
    "seam depth",
    "depth of occurrence",
    "geological formation",
    "geological structure",
    "geological section",
    "geological report",
    "geological exploration report",
    "exploration report",
    "coal quality",
    "volatile matter",
    "fixed carbon",
    "seam horizon",
    "seam horizons",
    "parting thickness",
    "thickness of the parting",
    "thickness of parting",
    "minimum workable thickness",
    "workable thickness",
)

GEOLOGICAL_CONCEPT_CUES: tuple[str, ...] = (
    "seam",
    "seams",
    "borehole",
    "boreholes",
    "drilling",
    "lithology",
    "sandstone",
    "shale",
    "formation",
    "formations",
    "fault",
    "stratigraphy",
    "exploration",
    "resource",
    "reserve",
    "reserves",
    "resources",
    "parting",
    "partings",
)

# Ordered longest-cue-first geological metrics (never map "coal seam" → mining "coal").
GEOLOGICAL_METRIC_CUES: dict[str, tuple[str, ...]] = {
    "seam_parting_thickness": (
        "thickness of the parting",
        "thickness of parting",
        "parting thickness",
        "thickness of partings",
    ),
    "formation_thickness": (
        "thickness of the formation",
        "thickness of formation",
        "formation thickness",
        "average thickness of the formation",
        "how thick is the formation",
    ),
    "overburden_thickness": (
        "overburden thickness",
        "thickness of overburden",
        "thickness of the overburden",
    ),
    "seam_thickness": (
        "seam thickness",
        "thickness of the coal seams",
        "thickness of the coal seam",
        "thickness of coal seams",
        "thickness of the seams",
        "thickness of the seam",
        "thickness of seam",
        "thickness of seams",
        "how thick is the seam",
        "how thick are the seams",
        "how thick is seam",
    ),
    "minimum_workable_seam_thickness": (
        "minimum workable thickness",
        "workable thickness",
        "minimum thickness considered",
        "min workable thickness",
    ),
    "borehole_depth": (
        "borehole depth",
        "depth of the borehole",
        "depth of borehole",
        "how deep was borehole",
        "how deep is borehole",
        "how deep was the borehole",
    ),
    "seam_depth": (
        "seam depth",
        "depth of occurrence",
        "depth of the seam",
        "depth of coal seams",
        "how deep is the seam",
    ),
    "coal_quality": ("coal quality", "ash content", "gcv"),
    "geological_structure": ("geological structure", "geological structures", "fault"),
    "formation": ("geological formation", "formations", "formation"),
    "lithology": ("lithology", "sandstone", "shale"),
    "borehole": ("boreholes", "borehole", "drilling"),
    "seam": (
        "coal seam horizons",
        "coal seam horizon",
        "coal seams",
        "coal seam",
        "seam horizons",
        "seam horizon",
        "seams",
        "seam",
    ),
    "resource": (
        "inferred resource",
        "indicated resource",
        "measured resource",
        "geological resource",
        "resource estimate",
        "resource quantity",
        "resource for",
        "resources for",
        "resources of coal",
        "coal resource",
        "gross inferred resource",
        "total inferred resource",
        "inferred resources",
        "resources",
        "resource",
    ),
    "reserve": (
        "inferred reserve",
        "indicated reserve",
        "measured reserve",
        "proved reserve",
        "probable reserve",
        "geological reserve",
        "coal reserve",
        "reserve estimate",
        "reserve quantity",
        "reserves",
        "reserve",
    ),
}

# Narrative suffixes stripped from entity/document references (generic).
_ENTITY_DOC_SUFFIXES: tuple[str, ...] = (
    r"geological\s+exploration\s+report",
    r"exploration\s+report",
    r"geological\s+report",
    r"annual\s+report",
    r"technical\s+report",
    r"assessment",
    r"study",
    r"exploration",
    r"report",
    r"document",
    r"pdf",
)

DOC_NARRATIVE_CUES = (
    "what does",
    "report say",
    "says about",
    "according to",
    "in the document",
    "in the report",
    "in the annual report",
    "mention",
    "described",
    "explain why",
    "reasons",
    "geological",
    "characteristics",
    "performance",
    "identified",
    "exploration report",
)

HYBRID_CUES = (
    "and explain",
    "explain the trend",
    "explain why",
    "using the report",
    "using annual",
    "what the report says",
    "compare.*with what",
    "verified.*report",
    "report.*verified",
)


@dataclass
class QueryPlan:
    query_type: str  # structured | rag | hybrid | unresolved
    entity: Optional[str] = None
    entities: list[str] = field(default_factory=list)  # multi-entity compare
    metric: Optional[str] = None
    metrics: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    reporting_months: list[str] = field(default_factory=list)
    measure_types: list[str] = field(default_factory=list)  # during | upto
    comparison_mode: Optional[str] = None  # compare | change | rank | None
    want_chart: bool = False
    want_explanation: bool = False
    wants_document_context: bool = False
    prefers_numeric: bool = False
    raw_question: str = ""
    route_reason: str = ""
    # G1.1 — geological vs mining domain (generic; no hard-coded docs/answers)
    domain: str = "general"  # geological | mining | general
    is_geological: bool = False
    geological_intent: Optional[str] = None  # e.g. seam_listing | seam_thickness | comparison
    geological_metrics: list[str] = field(default_factory=list)
    # G2 — geological entity slots (safe-normalized; never hard-coded answers)
    geological_seam: Optional[str] = None
    geological_seams: list[str] = field(default_factory=list)
    geological_borehole: Optional[str] = None
    geological_formation: Optional[str] = None
    listing_intent: bool = False
    factual_intent: bool = False
    # Document isolation
    document_scope_mode: Optional[str] = None  # single_document | multi_document | cross_document_comparison
    deictic_document: bool = False
    cross_document: bool = False
    scoped_document_ids: list[str] = field(default_factory=list)


_MONTH_PATTERN = (
    r"January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)


def _extract_reporting_months(text: str) -> list[str]:
    from app.retrieval.table_reconstruct import normalize_month_token

    found: list[str] = []
    for m in re.finditer(rf"\b({_MONTH_PATTERN})\b", text, re.I):
        # Avoid matching "may" as modal verb when not month-like context — keep simple:
        # skip bare "may"/"april" only if clearly modal? Keep all calendar months.
        tok = m.group(1)
        if tok.lower() == "may" and not re.search(
            r"\b(?:in|of|during|upto|for)\s+may\b", text, re.I
        ):
            # "may" alone is ambiguous; require preposition
            continue
        norm = normalize_month_token(tok)
        if norm and norm not in found:
            found.append(norm)
    return found


def _extract_measure_types(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    if re.search(r"\bduring\b", lower):
        found.append("during")
    if re.search(r"\bup\s*to\b|\bupto\b|\bcumulative\b|\bytd\b", lower):
        found.append("upto")
    # "produce in March" without during/upto → prefer during (monthly production)
    if not found and _extract_reporting_months(text):
        found.append("during")
    return found


def _extract_periods(text: str) -> list[str]:
    found: list[str] = []
    # FY2024 / FY2024-25
    for m in re.finditer(r"\bFY\s?(20\d{2})(?:[-/](\d{2}|\d{4}))?\b", text, re.I):
        start = m.group(1)
        end = m.group(2)
        if end:
            end = end[-2:] if len(end) == 4 else end
            found.append(f"FY{start}-{end}")
        else:
            found.append(f"FY{start}")
    # Shorthand FY24 / fy25 (common spoken/typed form)
    for m in re.finditer(r"\bFY\s?(\d{2})\b", text, re.I):
        yy = m.group(1)
        # Avoid double-counting if already captured as FY20xx
        cand = f"FY20{yy}"
        if cand not in found and f"FY20{yy}-" not in "".join(found):
            found.append(cand)
    m = re.search(r"from\s+FY\s?(20\d{2}).{0,24}to\s+FY\s?(20\d{2})", text, re.I)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        lo, hi = min(a, b), max(a, b)
        found = [f"FY{y}" for y in range(lo, hi + 1)]
    # from fy24 to fy25
    m = re.search(r"from\s+FY\s?(\d{2}).{0,24}(?:to|and)\s+FY\s?(\d{2})", text, re.I)
    if m and not re.search(r"from\s+FY\s?20\d{2}", text, re.I):
        a, b = int(m.group(1)), int(m.group(2))
        lo, hi = min(a, b), max(a, b)
        found = [f"FY20{y:02d}" for y in range(lo, hi + 1)]
    for m in re.finditer(r"\b(20\d{2})\s*[-–/]\s*(20\d{2}|\d{2})\b", text):
        end = m.group(2)
        end = end[-2:] if len(end) == 4 else end
        found.append(f"FY{m.group(1)}-{end}")
    out: list[str] = []
    for p in found:
        if p not in out:
            out.append(p)
    return out


def _extract_metrics(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    ordered = sorted(METRIC_CUES.items(), key=lambda kv: -max(len(c) for c in kv[1]))
    for canonical, cues in ordered:
        if any(c in lower for c in cues):
            if canonical not in found:
                found.append(canonical)
    return found


def _has_mining_production_intent(text: str) -> bool:
    """True when the ask is about operational/production coal (not geological seams)."""
    lower = (text or "").lower()
    if any(p in lower for p in GEOLOGICAL_PHRASE_CUES):
        return False
    prod_verb = bool(
        re.search(
            r"\b(?:produce[sd]?|production|output|tonnage|dispatch|offtake|"
            r"how\s+much|target|achievement)\b",
            lower,
        )
    )
    commodity = bool(re.search(r"\b(?:coal|lignite|overburden)\b", lower))
    fy_or_month = bool(
        re.search(r"\bfy\s?\d|\bfy\s*20\d{2}\b", lower)
        or _extract_reporting_months(text)
    )
    return prod_verb and (commodity or fy_or_month)


def _is_geological_query(text: str) -> bool:
    """Detect geological/exploration intent without treating bare 'coal' as geology."""
    lower = (text or "").lower()
    if any(p in lower for p in GEOLOGICAL_PHRASE_CUES):
        return True
    if _has_mining_production_intent(text):
        return False
    has_concept = any(
        re.search(rf"\b{re.escape(c)}\b", lower) for c in GEOLOGICAL_CONCEPT_CUES
    )
    if not has_concept:
        return False
    # Document/exploration narrative with geo concepts
    if re.search(r"\b(?:report|exploration|geological|identified|mentioned)\b", lower):
        return True
    # Pure geo concept questions (lithology, formations, boreholes, seams)
    return True


def _extract_geological_metrics(text: str) -> list[str]:
    lower = (text or "").lower()
    found: list[str] = []
    ordered = sorted(
        GEOLOGICAL_METRIC_CUES.items(),
        key=lambda kv: -max(len(c) for c in kv[1]),
    )
    for canonical, cues in ordered:
        hit = False
        for c in cues:
            # Multi-word: substring OK; single token: require word boundary
            # (prevents "formation" matching inside "information")
            if " " in c:
                if c in lower:
                    hit = True
                    break
            elif re.search(rf"\b{re.escape(c)}\b", lower):
                hit = True
                break
        if hit and canonical not in found:
            found.append(canonical)

    # Subject-aware thickness/depth resolution (formation ≠ seam ≠ parting)
    from app.geology.metric_kinds import THICKNESS_METRICS, classify_query_thickness_metric

    subject_metric = classify_query_thickness_metric(text)
    if subject_metric:
        # Keep exactly one thickness/depth kind — never allow formation_thickness
        # to remain alongside seam_thickness (any-match filters would leak).
        drop = set(THICKNESS_METRICS) | {
            "seam_depth",
            "borehole_depth",
            "stratigraphic_depth",
        }
        drop.discard(subject_metric)
        found = [m for m in found if m not in drop and m != subject_metric]
        found = [subject_metric] + found
        if subject_metric == "formation_thickness":
            found = [m for m in found if m != "formation"]
        if subject_metric == "borehole_depth":
            found = [m for m in found if m != "borehole"]

    # Resource / reserve are factual metrics — never leave "seam" as primary
    # when the question asks for a resource/reserve quantity.
    if "resource" in found or "reserve" in found:
        # Keep resource vs reserve distinct; pick whichever matched first (longer cues win order).
        primary_rr = next(m for m in found if m in {"resource", "reserve"})
        found = [primary_rr] + [m for m in found if m not in {primary_rr, "seam"}]

    # Bare "thickness" + seam subject without explicit phrase
    elif "seam_thickness" not in found and re.search(r"\bthickness\b|\bhow\s+thick\b", lower):
        if re.search(r"\bseams?\b|\bcoal\s+seams?\b", lower):
            found = ["seam_thickness"] + [
                m for m in found if m not in THICKNESS_METRICS and m != "seam_thickness"
            ]
        elif re.search(r"\bformation\b", lower):
            found = ["formation_thickness"] + [
                m for m in found if m not in THICKNESS_METRICS | {"formation", "formation_thickness"}
            ]

    return found


def _strip_document_narrative_suffixes(phrase: str) -> str:
    """Remove generic report/document tails from an entity phrase."""
    p = (phrase or "").strip()
    if not p:
        return p
    prev = None
    while prev != p:
        prev = p
        for suf in _ENTITY_DOC_SUFFIXES:
            p = re.sub(rf"\s+{suf}\s*$", "", p, flags=re.I).strip()
            p = re.sub(rf"^{suf}\s+", "", p, flags=re.I).strip()
    # Drop trailing "the" fragments
    p = re.sub(r"^(the|a|an)\s+", "", p, flags=re.I).strip()
    p = re.sub(r"\s+(the|a|an)$", "", p, flags=re.I).strip()
    return p


def _geological_intent_label(
    metrics: list[str],
    *,
    listing: bool = False,
    comparison: bool = False,
) -> Optional[str]:
    if comparison:
        return "comparison"
    if not metrics:
        return "geological_listing" if listing else "geological"
    primary = metrics[0]
    if listing and primary in {
        "seam",
        "borehole",
        "lithology",
        "formation",
        "geological_structure",
    }:
        return f"{primary}_listing"
    return primary


_METRIC_STOPWORDS = {
    "overburden",
    "lignite",
    "coal",
    "production",
    "performance",
    "figures",
    "actual",
    "annual",
    "report",
    "the year",
    "financial",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    # Geological concept words — never treat as entity names
    "thickness",
    "depth",
    "seam",
    "seams",
    "lithology",
    "formation",
    "formations",
    "borehole",
    "boreholes",
    "fault",
    "structure",
    "exploration",
    "quality",
    "sandstone",
    "shale",
    "drilling",
    "stratigraphy",
    "reserve",
    "reserves",
    "resource",
    "resources",
}


def _looks_like_period_token(phrase: str) -> bool:
    p = phrase.strip()
    if re.fullmatch(r"FY\s?\d{2,4}(?:\s*[-/]\s*\d{2,4})?", p, re.I):
        return True
    if re.fullmatch(r"20\d{2}(?:\s*[-/]\s*(?:20\d{2}|\d{2}))?", p):
        return True
    if re.search(r"\bfy\s?\d{2,4}\b", p, re.I) and len(p.split()) <= 3:
        # e.g. "the fy25", "fy24 and fy25"
        if all(
            re.fullmatch(r"(the|and|or|fy\d{2,4}|fy\s?\d{2,4})", t, re.I)
            for t in p.split()
        ):
            return True
    return False


def _extract_comparison_mode(text: str) -> Optional[str]:
    lower = (text or "").lower()
    if re.search(
        r"\b(?:which\s+(?:year|one|entity|company|state)\s+(?:had|has|is|was)\s+"
        r"(?:higher|lower|greater|less|more)|higher\s+or\s+lower|"
        r"who\s+(?:produced|had)\s+more)\b",
        lower,
    ):
        return "rank"
    if re.search(
        r"\b(?:change|difference|increase|decrease|growth|"
        r"year[- ]?over[- ]?year|yoy)\b|\bfrom\s+fy\s*\d",
        lower,
    ):
        return "change"
    if re.search(r"\b(?:compare|comparison|versus|vs\.?|against)\b", lower):
        return "compare"
    # "between FY24 and FY25" without other cues still implies change/compare
    if re.search(r"\bbetween\s+fy\s*\d", lower) and re.search(r"\band\s+fy\s*\d", lower):
        return "change"
    return None


def _looks_like_seam_label(phrase: str) -> bool:
    """True when the phrase is a seam id (not a mine/document/org entity).

    Important: do NOT treat mining acronyms like CIL/ECL/BCCL as roman seam labels
    (those letters overlap the roman numeral alphabet).
    """
    p = re.sub(r"\s+", " ", (phrase or "").strip())
    if not p:
        return False
    if re.fullmatch(r"(?i)seam\s+.+", p):
        return True
    # Short coal-seam style romans / digits only (not C/L/D/M org codes)
    if re.fullmatch(
        r"(?i)(i{1,3}|iv|v|vi{0,3}|ix|x{1,3})(\s+(top|bottom))?",
        p,
    ):
        return True
    if re.fullmatch(r"(?i)\d{1,3}(\s+(top|bottom))?", p):
        return True
    return False


def _clean_entity_phrase(phrase: str) -> Optional[str]:
    p = re.sub(r"^(the|a|an)\s+", "", (phrase or "").strip(), flags=re.I).strip()
    p = _strip_document_narrative_suffixes(p)
    # Strip trailing metric / measure / month / FY tokens repeatedly
    stop_tail = (
        r"production|coal|lignite|output|tonnage|during|upto|target|actual|"
        r"in|of|for|by|and|vs|versus|with|against|"
        r"january|february|march|april|may|june|july|august|september|october|november|december|"
        r"fy\s?\d{2,4}(?:\s*[-/]\s*\d{2,4})?"
    )
    prev = None
    while prev != p:
        prev = p
        p = re.sub(rf"\s+(?:{stop_tail})\s*$", "", p, flags=re.I).strip()
        p = re.sub(rf"^(?:{stop_tail})\s+", "", p, flags=re.I).strip()
        p = _strip_document_narrative_suffixes(p)
    if not p or _looks_like_period_token(p) or p.lower() in _METRIC_STOPWORDS:
        return None
    if _looks_like_seam_label(p):
        return None
    if re.fullmatch(r"fy\s*\d{2,4}", p, re.I):
        return None
    # Preserve slash-compound names (Captive/Others); only title fully-lowercase phrases
    if p.islower():
        if "/" in p:
            p = "/".join(part.title() for part in p.split("/"))
        else:
            p = p.title()
    return p


def _extract_entities(text: str, primary: Optional[str] = None) -> list[str]:
    """Extract one or more entities for comparison queries (generic)."""
    found: list[str] = []

    def _add(raw: Optional[str]) -> None:
        cleaned = _clean_entity_phrase(raw or "")
        if not cleaned:
            return
        if _looks_like_period_token(cleaned) or re.match(r"fy\s*\d", cleaned, re.I):
            return
        key = cleaned.lower().replace(" ", "")
        if any(e.lower().replace(" ", "") == key for e in found):
            return
        found.append(cleaned)

    # Single org-like token (allows Captive/Others); optional 1–2 more name tokens
    _ENT = r"[A-Za-z][A-Za-z0-9/&._-]*(?:\s+[A-Za-z][A-Za-z0-9/&._-]*){0,2}"
    _STOP = (
        r"production|coal|lignite|output|tonnage|during|upto|target|actual|"
        r"in|for|of|by|january|february|march|april|may|june|july|august|"
        r"september|october|november|december|fy\s?\d"
    )

    # compare A and B (case-insensitive; allow slash names; stop before metrics/months)
    m = re.search(
        rf"\bcompare\s+({_ENT})\s+(?:and|vs\.?|versus|with|against)\s+({_ENT})"
        rf"(?=\s+(?:{_STOP})\b|[.,?]|$)",
        text,
        re.I,
    )
    if m:
        left, right = m.group(1), m.group(2)
        if not re.match(r"fy\s*\d", left, re.I) and not re.match(r"fy\s*\d", right, re.I):
            _add(left)
            _add(right)

    # production of A and B / between A and B
    if len(found) < 2:
        m = re.search(
            rf"\b(?:of|between)\s+({_ENT})\s+and\s+({_ENT})"
            rf"(?=\s+(?:{_STOP})\b|[.,?]|$)",
            text,
            re.I,
        )
        if m:
            left, right = m.group(1), m.group(2)
            if not re.match(r"fy\s*\d", left, re.I) and not re.match(r"fy\s*\d", right, re.I):
                found = []
                _add(left)
                _add(right)

    if len(found) < 2:
        # Single-entity questions: use primary / single extractor only
        found = []
        if primary:
            _add(primary)
        else:
            single = _extract_entity(text, None)
            if single:
                _add(single)

    return found


def _extract_entity(text: str, prior: Optional[str] = None) -> Optional[str]:
    """Extract likely entity phrases from language — not a fixed org→route table."""
    m = re.search(r"\(([A-Za-z][A-Za-z0-9 ./&-]{1,60})\)", text)
    if m and not _looks_like_period_token(m.group(1)):
        return m.group(1).strip()

    m = re.search(
        r"\b(?:the\s+)?([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,4})\s+reports?\b",
        text,
    )
    if m and not _looks_like_period_token(m.group(1)):
        return m.group(1).strip()

    # "did <entity> produce/generate/mine" — before bare "mine <x>" so
    # "Gamma Mine produce" is not parsed as entity "Mine Produce".
    # Allow / & - inside names (e.g. Captive/Others) — generic, not org-specific.
    m = re.search(
        r"\bdid\s+([A-Za-z][A-Za-z0-9/&._-]*(?:\s+[A-Za-z][A-Za-z0-9/&._-]*){0,4})\s+"
        r"(?:produce|produced|generate|generated|mine|mined|export|exported)\b",
        text,
        re.I,
    )
    if m:
        phrase = m.group(1).strip()
        if phrase.lower() not in _METRIC_STOPWORDS and not _looks_like_period_token(phrase):
            return phrase.title() if phrase.islower() else phrase

    # "what was <entity> coal/production …" / "how much was <entity> …"
    # Skip when geological phrases like "coal seams" are present (not an org+coal ask).
    if not any(p in text.lower() for p in GEOLOGICAL_PHRASE_CUES):
        m = re.search(
            r"\b(?:what(?:\s+was|\s+is|\s+were|'s)?|how\s+much(?:\s+was|\s+is|\s+were)?|"
            r"show(?:\s+me)?)\s+"
            r"(?:the\s+)?"
            r"([A-Za-z][A-Za-z0-9/&._-]*(?:\s+[A-Za-z][A-Za-z0-9/&._-]*){0,4})\s+"
            r"(?:coal|lignite|production|output|tonnage)\b",
            text,
            re.I,
        )
        if m:
            phrase = m.group(1).strip()
            if phrase.lower() not in _METRIC_STOPWORDS and not _looks_like_period_token(phrase):
                return phrase.title() if phrase.islower() else phrase

    # Mine <token> before "from FY..." so periods do not steal the entity
    # Only when "mine" starts the name (not "... Mine produce").
    m = re.search(
        r"(?:^|[\s\"'(])mine\s+([a-z0-9][\w\-]*)(?:'s)?\b(?!\s+(?:produce|produced|generate|coal|lignite))",
        text,
        re.I,
    )
    if m:
        # Reject if a capitalized token immediately precedes "mine" (e.g. Gamma Mine)
        start = m.start()
        before = text[max(0, start - 24) : start]
        if not re.search(r"[A-Za-z0-9]\s+$", before):
            token = m.group(1)
            return f"Mine {token.upper()}" if len(token) <= 2 else f"Mine {token.title()}"

    # "production of/in/for/from <entity>"
    m = re.search(
        r"\b(?:production|output|tonnage)\s+(?:of|in|for|from|by)\s+"
        r"([A-Za-z][A-Za-z0-9/&._-]*(?:\s+[A-Za-z][A-Za-z0-9/&._-]*){0,4})\b",
        text,
        re.I,
    )
    if m:
        phrase = m.group(1).strip()
        if phrase.lower() not in _METRIC_STOPWORDS and not _looks_like_period_token(phrase):
            return phrase.title() if phrase.islower() else phrase

    # about/for/from/at — collect non-period candidates; prefer the last
    candidates: list[str] = []
    for m in re.finditer(
        r"\b(?:about|for|from|at|regarding|in)\s+([A-Z][A-Za-z0-9/&._-]+(?:\s+[A-Z][A-Za-z0-9/&._-]*){0,4})\b",
        text,
    ):
        phrase = m.group(1).strip()
        if not _looks_like_period_token(phrase) and phrase.lower() not in _METRIC_STOPWORDS:
            candidates.append(phrase)
    for m in re.finditer(
        r"\b(?:about|for|from|at|regarding|in)\s+([a-z][a-z0-9/&._-]+(?:\s+[a-z][a-z0-9/&._-]*){0,4})\b",
        text,
        re.I,
    ):
        phrase = m.group(1).strip()
        if phrase.lower() in _METRIC_STOPWORDS or _looks_like_period_token(phrase):
            continue
        # skip fy-like / year words
        if re.fullmatch(r"fy\d{2,4}", phrase, re.I):
            continue
        candidates.append(phrase.title() if phrase.islower() else phrase)
    # Drop period-like / article-only candidates
    cleaned: list[str] = []
    for phrase in candidates:
        p = re.sub(r"^(the|a|an)\s+", "", phrase, flags=re.I).strip()
        if not p or _looks_like_period_token(p) or re.fullmatch(r"fy\d{2,4}", p, re.I):
            continue
        if any(re.fullmatch(r"fy\d{2,4}", t, re.I) for t in p.split()):
            continue
        cleaned.append(p)
    if cleaned:
        return cleaned[-1]

    for m in re.finditer(r"\b([A-Z]{3,}[A-Za-z0-9]*)\b", text):
        tok = m.group(1)
        up = tok.upper()
        if up in {"FY", "MT", "PDF", "CSV", "XLSX", "API", "RAG", "LLM", "COMPARE", "WHICH", "WHAT", "SHOW"}:
            continue
        if up.startswith("FY") and up[2:].replace("-", "").isdigit():
            continue
        if _looks_like_period_token(tok):
            continue
        return tok

    # Title-case multi-word entities (skip leading question verbs)
    for m in re.finditer(
        r"\b((?:[A-Z][a-z0-9]+)(?:\s+[A-Z][a-z0-9]+){0,3})\b",
        text,
    ):
        phrase = m.group(1).strip()
        low = phrase.lower()
        if low in {"compare", "which", "what", "show", "how"}:
            continue
        if low.startswith(("what ", "how ", "show ", "compare ", "which ")):
            phrase = re.sub(
                r"^(?:what|how|show|compare|which)\s+",
                "",
                phrase,
                flags=re.I,
            ).strip()
            low = phrase.lower()
        if (
            phrase
            and low not in _METRIC_STOPWORDS
            and not _looks_like_period_token(phrase)
            and not low.startswith(("what ", "how ", "show ", "compare ", "which "))
            and not re.match(r"fy\s*\d", phrase, re.I)
        ):
            # Prefer phrases that look like names (at least one token not a month/metric)
            return phrase

    # "Compare <Entity> coal/production ..."
    m = re.search(
        r"\b(?:compare|change\s+in|difference\s+in)\s+"
        r"([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3})\s+"
        r"(?:coal|lignite|production|output|tonnage|produce|producing)\b",
        text,
    )
    if m:
        phrase = m.group(1).strip()
        if phrase.lower() not in _METRIC_STOPWORDS and not _looks_like_period_token(phrase):
            return phrase

    return prior


def parse_query(
    question: str,
    *,
    prior_entity: Optional[str] = None,
    prior_metric: Optional[str] = None,
    prior_seam: Optional[str] = None,
    prior_borehole: Optional[str] = None,
    prior_formation: Optional[str] = None,
) -> QueryPlan:
    q = (question or "").strip()
    lower = q.lower()

    is_geological = _is_geological_query(q)
    mining_prod = _has_mining_production_intent(q)

    # Pronoun / "its" follow-ups inherit geological domain from session context
    follow_up_geo = bool(
        prior_seam or prior_borehole or prior_formation
    ) and bool(
        re.search(
            r"\b(?:its|their|that|this)\b|\bthickness\b|\bdepth\b|\blithology\b|\bformation\b",
            lower,
        )
    )
    if follow_up_geo and not mining_prod and not is_geological:
        is_geological = True

    entity_now = _extract_entity(q, None)
    if entity_now:
        entity_now = _clean_entity_phrase(entity_now)
    if entity_now and _looks_like_period_token(entity_now):
        entity_now = None
    if entity_now and _looks_like_seam_label(entity_now):
        entity_now = None

    geological_metrics: list[str] = []
    geo_seam: Optional[str] = None
    geo_seams: list[str] = []
    geo_borehole: Optional[str] = None
    geo_formation: Optional[str] = None
    listing_intent = False
    factual_intent = False

    if is_geological:
        from app.geology.entities import (
            extract_borehole_from_question,
            extract_formation_from_question,
            extract_seam_from_question,
            extract_seams_from_question,
            is_listing_intent,
        )

        geological_metrics = _extract_geological_metrics(q)
        metrics = list(geological_metrics)
        # Never keep mining "coal" when geological phrases drove the intent
        metrics = [m for m in metrics if m != "coal"]
        domain = "geological"

        geo_seams = extract_seams_from_question(q)
        geo_seam = geo_seams[0] if geo_seams else extract_seam_from_question(q)
        geo_borehole = extract_borehole_from_question(q)
        geo_formation = extract_formation_from_question(q)

        # Safe follow-up: inherit prior geo entity only when unambiguous and not overridden
        if not geo_seam and prior_seam and re.search(
            r"\b(?:its|their|that|this|thickness|depth|formation)\b", lower
        ):
            geo_seam = prior_seam
            geo_seams = [prior_seam]
        if not geo_borehole and prior_borehole and re.search(
            r"\b(?:its|their|that|this|depth|lithology)\b", lower
        ):
            geo_borehole = prior_borehole
        if not geo_formation and prior_formation and re.search(
            r"\b(?:its|their|that|this|thickness)\b", lower
        ):
            geo_formation = prior_formation

        # Follow-up "what is its thickness?" with prior seam → seam_thickness
        if geo_seam and not metrics and re.search(r"\bthickness\b|\bhow\s+thick\b", lower):
            metrics = ["seam_thickness"]
            geological_metrics = ["seam_thickness"]
        if geo_borehole and not metrics and re.search(r"\bdepth\b|\bhow\s+deep\b", lower):
            metrics = ["borehole_depth"]
            geological_metrics = ["borehole_depth"]
        if geo_formation and not metrics and re.search(r"\bthickness\b", lower):
            metrics = ["formation_thickness"]
            geological_metrics = ["formation_thickness"]
        # Drop question-word false formations ("What Formation")
        if geo_formation:
            from app.geology.entities import is_plausible_formation_name

            if not is_plausible_formation_name(geo_formation, context=q):
                geo_formation = None

        listing_intent = is_listing_intent(q, metrics or geological_metrics)
        factual_intent = bool(metrics) and not listing_intent
    else:
        metrics = _extract_metrics(q)
        # Bare "coal" without production verbs and with report narrative stays non-mining
        if (
            metrics == ["coal"]
            and not mining_prod
            and re.search(r"\b(?:report|document|exploration|identified)\b", lower)
        ):
            # Ambiguous — prefer document/RAG without forcing coal production metric
            metrics = []
            domain = "general"
        else:
            domain = "mining" if (mining_prod or metrics or _extract_periods(q)) else "general"

    periods = _extract_periods(q)
    reporting_months = _extract_reporting_months(q)
    measure_types = _extract_measure_types(q)
    comparison_mode = _extract_comparison_mode(q)
    if is_geological and comparison_mode and geo_seams and len(geo_seams) >= 2:
        factual_intent = True
        listing_intent = False
    entities = _extract_entities(q, primary=entity_now)
    # Clean narrative suffixes on multi-entity list too
    cleaned_entities: list[str] = []
    for e in entities:
        ce = _clean_entity_phrase(e) or e
        ce = re.sub(r"[.,;:]+$", "", (ce or "").strip())
        if ce and ce not in cleaned_entities:
            cleaned_entities.append(ce)
    entities = cleaned_entities
    # Geological multi-seam compare: surface seams as entities for structured retrieval
    if is_geological and geo_seams and len(geo_seams) >= 2 and comparison_mode:
        for s in geo_seams:
            if s not in entities:
                entities.append(s)
    want_chart = any(k in lower for k in ("chart", "graph", "trend", "compare", "across years", "from fy"))
    want_explanation = any(k in lower for k in ("explain", "why", "reason", "reasons"))
    wants_document_context = (
        is_geological
        or any(k in lower for k in DOC_NARRATIVE_CUES)
        or bool(re.search(r"\breports?\b", lower))
    )
    # Geological identification / narrative asks are not mining numeric production queries
    prefers_numeric = False
    if not is_geological:
        prefers_numeric = any(
            k in lower
            for k in (
                "what was",
                "how much",
                "how many",
                "figures",
                "value",
                "actual",
                "show",
                "compare",
                "chart",
                "graph",
                "trend",
                "change",
                "difference",
                "higher",
                "lower",
                "increase",
                "decrease",
            )
        ) or bool(comparison_mode)
    hybrid_intent = any(re.search(h, lower) for h in HYBRID_CUES) or (
        want_chart and want_explanation
    ) or (
        prefers_numeric and wants_document_context and want_explanation
    )
    if is_geological and geological_metrics and wants_document_context:
        # Structured geo facts + narrative often both useful
        hybrid_intent = True
    # Listing / factual geo asks prefer structured-first (still hybrid when RAG helps)
    if is_geological and (listing_intent or factual_intent or geo_seam or geo_borehole):
        hybrid_intent = True

    entity = entity_now or (entities[0] if entities else None)
    if entity:
        entity = _clean_entity_phrase(entity) or entity
    metric = metrics[0] if metrics else None
    geological_intent = (
        _geological_intent_label(
            geological_metrics or metrics,
            listing=listing_intent,
            comparison=bool(comparison_mode and is_geological),
        )
        if is_geological
        else None
    )

    from app.assistant.document_resolver import is_cross_document_query, is_deictic_document_query

    deictic_document = is_deictic_document_query(q)
    cross_document = is_cross_document_query(q) or (
        bool(comparison_mode) and not is_geological
    )
    # Explicit geo multi-entity compare may span documents only when user asks across docs
    if is_geological and comparison_mode and is_cross_document_query(q):
        cross_document = True

    if prior_entity and (periods or "what about" in lower) and not entity_now and not entities:
        if not deictic_document:
            entity = prior_entity
            entities = [prior_entity]
    # Geological follow-ups without a new entity keep the prior document/entity,
    # EXCEPT when the user says "this report/document" (current-doc deixis).
    if (
        is_geological
        and prior_entity
        and not entity_now
        and not deictic_document
        and not cross_document
    ):
        entity = prior_entity
        if prior_entity not in entities:
            entities = [prior_entity] + list(entities)
    if deictic_document and not cross_document:
        # Deixis must not keep a stale named place from a previous turn
        entity = None
        entities = []
    if prior_metric and (periods or "what about" in lower) and not metrics:
        if not is_geological:
            metric = prior_metric
            metrics = [prior_metric]

    # Multi-FY without explicit compare cues still enables change when asked "between"
    if comparison_mode is None and len(periods) >= 2 and prefers_numeric:
        if any(k in lower for k in ("both", "each", "respectively")):
            comparison_mode = "compare"
        elif re.search(r"\b(?:fy\s*\d).*(?:fy\s*\d)", lower):
            # "for FY24 and FY25" listing — treat as compare when phrasing asks compare/change elsewhere only
            if re.search(r"\bcompare\b|\bchange\b|\bdifference\b|\bhigher\b", lower):
                comparison_mode = "compare"

    if is_geological:
        if hybrid_intent or listing_intent or factual_intent:
            tentative = "prefer_hybrid"
        else:
            tentative = "prefer_rag"
    elif hybrid_intent:
        tentative = "prefer_hybrid"
    elif wants_document_context and not prefers_numeric:
        tentative = "prefer_rag"
    elif prefers_numeric or metrics or periods:
        tentative = "prefer_structured"
    else:
        tentative = "prefer_rag"

    scope_mode = None
    if cross_document:
        scope_mode = "cross_document_comparison"
    elif deictic_document:
        scope_mode = "single_document"

    return QueryPlan(
        query_type=tentative,
        entity=entity,
        entities=entities,
        metric=metric,
        metrics=metrics,
        periods=periods,
        reporting_months=reporting_months,
        measure_types=measure_types,
        comparison_mode=comparison_mode,
        want_chart=want_chart,
        want_explanation=want_explanation,
        wants_document_context=wants_document_context,
        prefers_numeric=prefers_numeric,
        raw_question=q,
        route_reason="parsed",
        domain=domain,
        is_geological=is_geological,
        geological_intent=geological_intent,
        geological_metrics=list(geological_metrics),
        geological_seam=geo_seam,
        geological_seams=list(geo_seams),
        geological_borehole=geo_borehole,
        geological_formation=geo_formation,
        listing_intent=listing_intent,
        factual_intent=factual_intent,
        document_scope_mode=scope_mode,
        deictic_document=deictic_document,
        cross_document=cross_document,
    )


def _metrics_to_probe(plan: QueryPlan) -> list[str]:
    """Prefer specific metrics over bare 'production' when both appear."""
    metrics = list(plan.metrics or ([plan.metric] if plan.metric else []))
    if not metrics:
        return []
    specific = [m for m in metrics if m != "production"]
    return specific if specific else metrics


def structured_evidence_available(db: Session, plan: QueryPlan) -> bool:
    """True only if CURRENT verified structured DB has matching rows.

    Requires a resolved entity so metric+period alone cannot match an unrelated org.
    Geological plans may match verified GeologicalFact rows (entity optional when
    document context is implied by geo metrics alone — still scoped in retriever).
    """
    from app.assistant.structured_retriever import retrieve_structured_facts

    if getattr(plan, "is_geological", False):
        from app.assistant.geological_retriever import geological_structured_available

        return geological_structured_available(db, plan)

    if not plan.entity:
        return False

    metrics = _metrics_to_probe(plan)

    if metrics:
        for m in metrics:
            hits = retrieve_structured_facts(
                db,
                entity=plan.entity,
                metric=m,
                periods=plan.periods or None,
                verified_only=True,
            )
            if hits:
                return True
        if plan.periods:
            for m in metrics:
                hits = retrieve_structured_facts(
                    db,
                    entity=plan.entity,
                    metric=m,
                    periods=None,
                    verified_only=True,
                )
                if hits:
                    return True
        return False

    hits = retrieve_structured_facts(
        db,
        entity=plan.entity,
        metric=None,
        periods=plan.periods or None,
        verified_only=True,
    )
    return bool(hits)


def rag_evidence_available(db: Session, plan: QueryPlan, *, top_k: int = 3) -> bool:
    from app.assistant.rag_retriever import retrieve_rag_evidence

    hits = retrieve_rag_evidence(db, plan.raw_question, top_k=top_k, plan=plan)
    return bool(hits)


def resolve_route(db: Session, plan: QueryPlan) -> QueryPlan:
    """Commit to structured/rag/hybrid using actual evidence availability."""
    has_structured = structured_evidence_available(db, plan)

    need_rag_probe = (
        plan.query_type == "prefer_hybrid"
        or plan.wants_document_context
        or plan.want_explanation
        or not has_structured
        or plan.query_type == "prefer_rag"
    )
    has_rag = rag_evidence_available(db, plan) if need_rag_probe else False

    if plan.query_type == "prefer_hybrid" or (
        has_structured and has_rag and (plan.want_explanation or plan.wants_document_context)
    ):
        if has_structured and has_rag:
            plan.query_type = "hybrid"
            plan.route_reason = "structured_and_rag_evidence"
        elif has_structured:
            plan.query_type = "structured"
            plan.route_reason = "structured_only_for_hybrid_intent"
        elif has_rag:
            plan.query_type = "rag"
            plan.route_reason = "rag_fallback_no_structured"
        else:
            plan.query_type = "rag"
            plan.route_reason = "no_evidence_attempt_rag"
        return plan

    if has_structured and not plan.wants_document_context:
        plan.query_type = "structured"
        plan.route_reason = "verified_structured_match"
        return plan

    if has_structured and plan.wants_document_context and not has_rag:
        plan.query_type = "structured"
        plan.route_reason = "structured_match_doc_cue_but_no_rag"
        return plan

    if has_rag:
        plan.query_type = "rag"
        plan.route_reason = (
            "rag_match_no_structured" if not has_structured else "document_narrative"
        )
        return plan

    if has_structured:
        plan.query_type = "structured"
        plan.route_reason = "structured_last_resort"
        return plan

    plan.query_type = "rag"
    plan.route_reason = "no_structured_attempt_rag"
    return plan


def route_query(
    question: str,
    *,
    prior_entity: Optional[str] = None,
    prior_metric: Optional[str] = None,
    prior_seam: Optional[str] = None,
    prior_borehole: Optional[str] = None,
    prior_formation: Optional[str] = None,
    db: Optional[Session] = None,
) -> QueryPlan:
    """Parse (+ optionally resolve with DB)."""
    plan = parse_query(
        question,
        prior_entity=prior_entity,
        prior_metric=prior_metric,
        prior_seam=prior_seam,
        prior_borehole=prior_borehole,
        prior_formation=prior_formation,
    )
    if db is not None:
        return resolve_route(db, plan)

    if plan.query_type == "prefer_hybrid":
        plan.query_type = "hybrid"
    elif plan.query_type == "prefer_structured":
        plan.query_type = "structured" if (plan.entity and plan.metric) else "rag"
        plan.route_reason = "parse_only_no_db"
    else:
        plan.query_type = "rag"
        plan.route_reason = "parse_only_prefer_rag"
    return plan
