"""Rule-based geological fact extraction from page text (no invented values)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.geology.taxonomy import COAL_QUALITY_PARAMS, LITHOLOGY_TERMS
from app.geology.units import canonicalize_length_unit, parse_number, to_metres
from app.geology.seam_ids import (
    COAL_SEAM_OF_FORMATION_RE,
    SEAM_CODE_BEFORE_RE,
    SEAM_OF_THICKNESS_RE,
    SEAM_QUALIFIED_RE,
    UNCORRELATED_SEAM_RE,
    is_valid_seam_identifier,
    normalize_seam_identifier,
)
from app.geology.entities import (
    is_plausible_formation_name,
    normalize_formation_name,
)


def _safe_formation_name(raw: Optional[str], *, context: Optional[str] = None) -> Optional[str]:
    """Accept only plausible geological formation names; normalize formatting."""
    if not raw:
        return None
    if not is_plausible_formation_name(raw, context=context):
        return None
    return normalize_formation_name(raw)


def _formation_raw_from_match(m: re.Match) -> str:
    """Combine optional Upper/Lower qualifier + name from _FORMATION_RE groups."""
    prefix = (m.group(1) or "").strip()
    name = (m.group(2) or "").strip()
    return f"{prefix} {name}".strip() if prefix else name


@dataclass
class GeologicalFactDraft:
    borehole_id: Optional[str] = None
    seam_name: Optional[str] = None
    seam_status: Optional[str] = None  # named | uncorrelated | unnamed
    depth: Optional[str] = None
    depth_unit: Optional[str] = None
    depth_normalized_m: Optional[float] = None
    thickness: Optional[str] = None
    thickness_unit: Optional[str] = None
    thickness_normalized_m: Optional[float] = None
    thickness_min: Optional[str] = None
    thickness_max: Optional[str] = None
    thickness_min_normalized_m: Optional[float] = None
    thickness_max_normalized_m: Optional[float] = None
    depth_min: Optional[str] = None
    depth_max: Optional[str] = None
    depth_min_normalized_m: Optional[float] = None
    depth_max_normalized_m: Optional[float] = None
    lithology: Optional[str] = None
    geological_formation: Optional[str] = None
    geological_structure: Optional[str] = None
    coal_quality_parameter: Optional[str] = None
    coal_quality_value: Optional[str] = None
    coal_quality_unit: Optional[str] = None
    original_value: Optional[str] = None
    original_unit: Optional[str] = None
    source_page: Optional[int] = None
    source_location: Optional[str] = None
    evidence_text: str = ""
    extraction_confidence: float = 0.0
    status: str = "extracted"
    warnings: list[str] = field(default_factory=list)
    table_context: Optional[str] = None
    metric_kind: Optional[str] = None


_BH_RE = re.compile(
    r"(?i)\b(?:bore\s*hole|borehole|drill\s*hole|dh)\s*(?:no\.?|number|#|:)?\s*([A-Z]{0,4}[-_]?\d{1,5}[A-Z]?)\b"
)

# Prefer longer / qualified seam labels first (Top/Bottom/roman/codes)
# Letter+digit codes (L1, R4) allowed; bare English words are not.
_SEAM_QUALIFIED_RE = SEAM_QUALIFIED_RE
_SEAM_OF_THICKNESS_RE = SEAM_OF_THICKNESS_RE
_SEAM_CODE_BEFORE_RE = SEAM_CODE_BEFORE_RE

_THICKNESS_RANGE_RE = re.compile(
    r"(?i)\b(?:thickness|seam\s+thickness)\b[\s\S]{0,160}?"
    r"(?:varies?|varying|ranging|range|general\s+thickness)\s+"
    r"(?:within[\s\S]{0,55}?)?"
    r"(?:(?:var(?:ies|ying)|ranging)\s+)?"
    r"(?:from|between)\s*"
    r"([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm|ft|feet|foot)?\s*"
    r"(?:to|[-–—]|and)\s*"
    r"([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm|ft|feet|foot)?"
)

# e.g. "general thickness 0.69m to 1.41m" / "thickness 0.55m to 0.85m"
_THICKNESS_RANGE_DIRECT_RE = re.compile(
    r"(?i)\b(?:general\s+thickness|thickness)\s+"
    r"([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm|ft|feet|foot)?\s*"
    r"(?:to|[-–—])\s*"
    r"([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm|ft|feet|foot)?"
)

_DEPTH_RE = re.compile(
    r"(?i)\b(?:depth|from\s+depth|at\s+depth)\s*(?:of|:)?\s*([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm|ft|feet|foot)?\b"
)
_THICKNESS_POINT_RE = re.compile(
    r"(?i)\b(?:minimum\s+thickness|maximum\s+thickness|thickness|seam\s+thickness|thick)\s*"
    r"(?:of|is|=|:)?\s*([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm|ft|feet|foot)?\b"
)
_WORKABLE_THICKNESS_RE = re.compile(
    r"(?i)\bminimum\s+workable\s+thickness\b"
    r"[\s\S]{0,100}?"
    r"(?:(?:has\s+been\s+)?considered\s+(?:for\s+[^.\\n]{0,60}?)?)?"
    r"(?:is|of|=|:)?\s*"
    r"([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm|ft|feet|foot)?"
)
_FORMATION_RE = re.compile(
    r"(?i)\b(?!(?:the|a|an|and|or|of|to|for|in|on|at|by|from|with|this|that|"
    r"through|into|what|which|where|when|who|how|overlies|underlies|overlie|underlie)\b)"
    r"((?:Upper|Lower|Middle)\s+)?"
    r"([A-Za-z][A-Za-z]{2,}(?:\s+[A-Za-z][A-Za-z]{2,})?)\s+Formations?\b"
)
# "average thickness of the <Name> Formation … is <min>-<max>m"
_FORMATION_THICKNESS_RE = re.compile(
    r"(?i)\b(?:average\s+)?thickness\s+of\s+(?:the\s+)?"
    r"([A-Za-z][A-Za-z\s-]{1,40}?)\s+Formation\b"
    r"[\s\S]{0,80}?"
    r"(?:is|of|=|:)?\s*"
    r"([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm|ft|feet|foot)?\s*"
    r"(?:to|[-–—])\s*"
    r"([+-]?\d+(?:[.,]\d+)?)\s*(m|meter|meters|metre|metres|cm|mm|ft|feet|foot)?"
)
_STRUCTURE_RE = re.compile(
    r"(?i)\b(fault|fold|anticline|syncline|thrust|unconformity)\b"
)


def _evidence_window(text: str, start: int, end: int, radius: int = 110) -> str:
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def _normalize_seam_label(raw: str) -> Optional[str]:
    """Build a canonical Seam … label from an explicit match; reject noise."""
    return normalize_seam_identifier(raw)


def _find_seam_near(text: str, pos: int, lookback: int = 400, lookahead: int = 100) -> Optional[str]:
    """Nearest explicit seam identifier before (or slightly after) a measure."""
    a = max(0, pos - lookback)
    b = min(len(text), pos + lookahead)
    chunk = text[a:b]
    rel = pos - a
    # Prefer "thickness of the seam X" in the window
    of_matches = list(_SEAM_OF_THICKNESS_RE.finditer(chunk))
    if of_matches:
        before = [m for m in of_matches if m.start() <= rel + 5]
        chosen = before[-1] if before else of_matches[-1]
        return _normalize_seam_label(chosen.group(1))
    # "R4 seam" / "III Top seam"
    before_code = list(_SEAM_CODE_BEFORE_RE.finditer(chunk))
    if before_code:
        before = [m for m in before_code if m.start() <= rel + 5]
        chosen = before[-1] if before else before_code[-1]
        return _normalize_seam_label(chosen.group(1))
    matches = list(_SEAM_QUALIFIED_RE.finditer(chunk))
    if not matches:
        return None
    before = [m for m in matches if m.start() <= rel]
    chosen = before[-1] if before else matches[0]
    return _normalize_seam_label(chosen.group(1))


def _find_borehole_near(text: str, pos: int, radius: int = 180) -> Optional[str]:
    a = max(0, pos - radius)
    b = min(len(text), pos + radius)
    m = _BH_RE.search(text[a:b])
    return m.group(1).upper() if m else None


def _attach_length(
    draft: GeologicalFactDraft,
    *,
    kind: str,
    value_raw: str,
    unit_raw: Optional[str],
) -> None:
    unit = canonicalize_length_unit(unit_raw) or (unit_raw.strip() if unit_raw else None)
    num = parse_number(value_raw)
    if kind == "depth":
        draft.depth = value_raw.replace(",", "")
        draft.depth_unit = unit
        if num is not None:
            draft.depth_normalized_m = to_metres(num, unit)
    else:
        draft.thickness = value_raw.replace(",", "")
        draft.thickness_unit = unit
        if num is not None:
            draft.thickness_normalized_m = to_metres(num, unit)


def _attach_thickness_range(
    draft: GeologicalFactDraft,
    *,
    min_raw: str,
    max_raw: str,
    unit_raw: Optional[str],
) -> None:
    unit = canonicalize_length_unit(unit_raw) or (unit_raw.strip() if unit_raw else "m")
    lo = parse_number(min_raw)
    hi = parse_number(max_raw)
    draft.thickness_min = min_raw.replace(",", "")
    draft.thickness_max = max_raw.replace(",", "")
    draft.thickness_unit = unit
    # Display value as range string (not an average)
    draft.thickness = f"{draft.thickness_min}–{draft.thickness_max}"
    if lo is not None:
        draft.thickness_min_normalized_m = to_metres(lo, unit)
    if hi is not None:
        draft.thickness_max_normalized_m = to_metres(hi, unit)
    # Keep normalized single field as min for sorting only (not an invented average)
    if draft.thickness_min_normalized_m is not None:
        draft.thickness_normalized_m = draft.thickness_min_normalized_m


def _score_draft(draft: GeologicalFactDraft) -> float:
    score = 0.4
    filled = 0
    for attr in (
        "borehole_id",
        "seam_name",
        "depth",
        "thickness",
        "thickness_min",
        "lithology",
        "geological_formation",
        "geological_structure",
        "coal_quality_parameter",
    ):
        if getattr(draft, attr):
            filled += 1
            score += 0.07
    if (draft.seam_status or "").lower() in {"uncorrelated", "unnamed"}:
        filled += 1
        score += 0.08
    if draft.seam_name and (draft.thickness or draft.thickness_min):
        score += 0.15  # associated measure bonus
    if draft.thickness_min and draft.thickness_max and draft.seam_name:
        score += 0.08  # explicit range with seam
    if draft.metric_kind == "formation_thickness" and draft.geological_formation:
        score += 0.12
    if draft.metric_kind == "minimum_workable_seam_thickness":
        score += 0.1
    if draft.evidence_text and len(draft.evidence_text) >= 12:
        score += 0.1
    if draft.source_page is not None:
        score += 0.05
    if draft.depth and draft.thickness and draft.depth == draft.thickness:
        draft.warnings.append("depth_equals_thickness_check")
        score -= 0.15
    if filled == 0:
        return 0.0
    return max(0.0, min(0.95, round(score, 3)))


def _status_for(confidence: float) -> str:
    from app.config import get_settings

    settings = get_settings()
    if confidence >= settings.high_confidence_threshold:
        return "high_confidence"
    return "review_required"


def _finalize(draft: GeologicalFactDraft) -> Optional[GeologicalFactDraft]:
    # Uncorrelated / unnamed seam entities are valid without an identifier
    status = (draft.seam_status or "").lower()
    is_unnamed_entity = status in {"uncorrelated", "unnamed"}

    has_payload = any(
        [
            draft.borehole_id,
            draft.seam_name,
            is_unnamed_entity,
            draft.depth,
            draft.thickness,
            draft.thickness_min,
            draft.lithology,
            draft.geological_formation,
            draft.geological_structure,
            draft.coal_quality_parameter,
            draft.original_value,
            (draft.metric_kind or "") in {
                "resource",
                "reserve",
                "resource_quantity",
                "reserve_quantity",
            },
        ]
    )
    if not has_payload:
        return None
    if draft.seam_name and not is_unnamed_entity and not is_valid_seam_identifier(draft.seam_name):
        # Drop noise seam labels unless other payload remains
        draft.warnings = list(draft.warnings or []) + ["invalid_seam_identifier"]
        draft.seam_name = None
        if not any(
            [
                draft.borehole_id,
                draft.depth,
                draft.thickness,
                draft.thickness_min,
                draft.lithology,
                draft.geological_formation,
                draft.geological_structure,
                draft.coal_quality_parameter,
                draft.original_value,
                is_unnamed_entity,
            ]
        ):
            return None
    elif draft.seam_name and not is_unnamed_entity:
        canon = normalize_seam_identifier(draft.seam_name)
        if canon:
            draft.seam_name = canon
            draft.seam_status = draft.seam_status or "named"
        else:
            draft.warnings = list(draft.warnings or []) + ["invalid_seam_identifier"]
            draft.seam_name = None
    # Never invent identifiers for uncorrelated/unnamed
    if is_unnamed_entity:
        draft.seam_name = None
    evidence_ok = bool(draft.evidence_text and len(draft.evidence_text.strip()) >= 8)
    if not evidence_ok:
        draft.warnings.append("missing_evidence")
        draft.extraction_confidence = 0.25
        draft.status = "review_required"
    else:
        draft.extraction_confidence = _score_draft(draft)
        draft.status = _status_for(draft.extraction_confidence)
        # Unnamed/uncorrelated identity is inherently lower confidence
        if is_unnamed_entity and draft.status == "high_confidence":
            draft.status = "review_required"
            draft.extraction_confidence = min(draft.extraction_confidence, 0.65)
    return draft


def extract_facts_from_page(
    text: str,
    *,
    page_number: int,
    source_location: Optional[str] = None,
) -> list[GeologicalFactDraft]:
    """Extract only values explicitly present in this page's text."""
    if not (text or "").strip():
        return []

    drafts: list[GeologicalFactDraft] = []
    used_spans: set[tuple[int, int]] = set()

    def _loc() -> str:
        return source_location or f"page:{page_number}"

    # ── Pass -1: uncorrelated / unnamed coal seams (no invented identifiers) ──
    for m in UNCORRELATED_SEAM_RE.finditer(text):
        span = (m.start(), m.end())
        used_spans.add(span)
        fm_name = (m.group(1) or "").strip()
        if not fm_name:
            # Look ahead / around for "of <Name> Formation"
            window = text[m.start() : min(len(text), m.end() + 80)]
            fm = _FORMATION_RE.search(window)
            if fm:
                fm_name = _formation_raw_from_match(fm)
        status = "uncorrelated" if re.search(r"(?i)\buncorrelated\b", m.group(0)) else "unnamed"
        ev = _evidence_window(text, m.start(), m.end(), radius=140)
        safe_fm = _safe_formation_name(fm_name, context=ev) if fm_name else None
        if not safe_fm:
            fm2 = _FORMATION_RE.search(ev or "")
            if fm2:
                safe_fm = _safe_formation_name(_formation_raw_from_match(fm2), context=ev)
        draft = GeologicalFactDraft(
            source_page=page_number,
            source_location=_loc(),
            evidence_text=ev,
            seam_name=None,
            seam_status=status,
            metric_kind="seam",
            geological_formation=safe_fm,
        )
        done = _finalize(draft)
        if done:
            drafts.append(done)

    # "a coal seam of X Formation" only when the surrounding sentence marks it uncorrelated/unnamed
    # or explicitly says the formation seam was left uncorrelated.
    for m in COAL_SEAM_OF_FORMATION_RE.finditer(text):
        span = (m.start(), m.end())
        if any(abs(span[0] - s0) < 20 for s0, _ in used_spans):
            continue
        ctx = text[max(0, m.start() - 120) : min(len(text), m.end() + 160)]
        if not re.search(
            r"(?i)\b(?:uncorrelated|unnamed|un-?named|left\s+uncorrelated|could\s+not\s+be\s+correlated)\b",
            ctx,
        ):
            continue
        # Skip if this is actually a named identifier + formation ("R4 seam of Raniganj")
        pre = text[max(0, m.start() - 24) : m.start()]
        if re.search(r"(?i)\b(?:[A-Za-z]{1,3}\d+[A-Za-z]?|[IVXLC]{1,6}|\d{1,3}[A-Za-z]?)\s+$", pre):
            continue
        used_spans.add(span)
        fm_name = re.sub(r"\s+", " ", (m.group(1) or "").strip())
        ev = _evidence_window(text, m.start(), m.end(), radius=160)
        draft = GeologicalFactDraft(
            source_page=page_number,
            source_location=_loc(),
            evidence_text=ev,
            seam_name=None,
            seam_status="uncorrelated",
            metric_kind="seam",
            geological_formation=_safe_formation_name(fm_name, context=ev),
        )
        done = _finalize(draft)
        if done:
            drafts.append(done)

    # ── Pass -0.5: minimum workable thickness (never R4 / named seam thickness) ──
    for m in _WORKABLE_THICKNESS_RE.finditer(text):
        span = (m.start(), m.end())
        if not m.group(1):
            continue
        used_spans.add(span)
        draft = GeologicalFactDraft(
            source_page=page_number,
            source_location=_loc(),
            evidence_text=re.sub(
                r"\s+",
                " ",
                text[m.start() : min(len(text), m.end() + 40)],
            ).strip(),
            seam_name=None,
            borehole_id=None,
            metric_kind="minimum_workable_seam_thickness",
        )
        _attach_length(
            draft, kind="thickness", value_raw=m.group(1), unit_raw=m.group(2) or "m"
        )
        # Guard: require a plausible thickness magnitude (reject OCR junk like "4")
        try:
            tv = float((draft.thickness or "0").replace(",", ""))
        except ValueError:
            tv = 0.0
        if tv <= 0 or tv > 50:  # workable seam thickness in metres is typically < 50m
            if (draft.thickness_unit or "m").lower() in {"m", "meter", "meters", "metre", "metres"}:
                continue
        done = _finalize(draft)
        if done:
            drafts.append(done)

    # ── Pass 0: formation thickness (never treat as seam thickness) ──
    for m in _FORMATION_THICKNESS_RE.finditer(text):
        span = (m.start(), m.end())
        used_spans.add(span)
        fm_name = re.sub(r"\s+", " ", (m.group(1) or "").strip())
        ev = re.sub(
            r"\s+",
            " ",
            text[m.start() : min(len(text), m.end() + 40)],
        ).strip()
        safe_fm = _safe_formation_name(fm_name, context=ev)
        if not safe_fm:
            continue
        draft = GeologicalFactDraft(
            source_page=page_number,
            source_location=_loc(),
            evidence_text=ev,
            geological_formation=safe_fm,
            seam_name=None,
            borehole_id=None,
            metric_kind="formation_thickness",
        )
        # groups: 1=name, 2=min, 3=unit?, 4=max, 5=unit?
        _attach_thickness_range(
            draft,
            min_raw=m.group(2),
            max_raw=m.group(4),
            unit_raw=m.group(3) or m.group(5) or "m",
        )
        done = _finalize(draft)
        if done:
            drafts.append(done)

    # ── Pass 1: thickness RANGES with seam association from nearby context ──
    range_iters = list(_THICKNESS_RANGE_RE.finditer(text)) + list(
        _THICKNESS_RANGE_DIRECT_RE.finditer(text)
    )
    for m in range_iters:
        span = (m.start(), m.end())
        if span in used_spans:
            continue
        # Skip heavily overlapping spans (same numbers matched twice)
        if any(abs(span[0] - s0) < 8 and abs(span[1] - s1) < 8 for s0, s1 in used_spans):
            continue
        # Formation thickness is handled in pass 0 — do not invent seam associations
        ctx_pre = text[max(0, m.start() - 80) : min(len(text), m.end() + 80)]
        if re.search(r"(?i)\bformation\b", ctx_pre) and not re.search(
            r"(?i)\bseams?\b", ctx_pre
        ):
            continue
        used_spans.add(span)
        unit = m.group(2) or m.group(4) or "m"
        draft = GeologicalFactDraft(
            source_page=page_number,
            source_location=_loc(),
            # Start at match (not far lookback) so preceding parting tables do not dominate
            evidence_text=re.sub(
                r"\s+",
                " ",
                text[m.start() : min(len(text), m.end() + 100)],
            ).strip(),
        )
        _attach_thickness_range(
            draft, min_raw=m.group(1), max_raw=m.group(3), unit_raw=unit
        )
        seam = _find_seam_near(text, m.end())
        if not seam:
            seam = _find_seam_near(text, m.start())
        if seam:
            draft.seam_name = seam
        # Block-level general thickness ranges are not borehole-specific
        if re.search(
            r"(?i)(?:varies?|varying)\s+within\s+the\s+block|general\s+thickness",
            draft.evidence_text or "",
        ):
            draft.borehole_id = None
        else:
            bh = _find_borehole_near(text, m.end())
            if not bh:
                bh = _find_borehole_near(text, m.start())
            if bh:
                draft.borehole_id = bh
        # Formation / structure in evidence window
        fm = _FORMATION_RE.search(draft.evidence_text or "")
        if fm:
            draft.geological_formation = _safe_formation_name(
                _formation_raw_from_match(fm), context=draft.evidence_text
            )
        sm = _STRUCTURE_RE.search(draft.evidence_text)
        if sm:
            draft.geological_structure = sm.group(1).lower()
        # Skip parting-table numeric pairs misread as seam thickness ranges
        ctx = text[max(0, m.start() - 200) : min(len(text), m.end() + 40)].lower()
        ev = draft.evidence_text or ""
        has_narrative = bool(
            re.search(
                r"(?i)(?:varies?|varying)\s+within|general\s+thickness\s+(?:vary|varying)|"
                r"general\s+thickness\s+[0-9]|thickness\s+of\s+(?:the\s+)?seam",
                ev,
            )
        )
        if "parting" in ctx and not has_narrative:
            continue
        # Prefer narrative range phrasing
        if not re.search(
            r"(?i)(?:varies?|varying|ranging|from|between|general\s+thickness)",
            ev,
        ):
            continue
        done = _finalize(draft)
        if done:
            drafts.append(done)

    # Dedupe competing range facts: same page + same min/max → keep best seam association
    range_groups: dict[tuple, list[GeologicalFactDraft]] = {}
    kept: list[GeologicalFactDraft] = []
    for d in drafts:
        if d.thickness_min and d.thickness_max:
            key = (d.source_page, d.thickness_min, d.thickness_max)
            range_groups.setdefault(key, []).append(d)
        else:
            kept.append(d)

    def _range_score(d: GeologicalFactDraft) -> int:
        ev = (d.evidence_text or "").lower()
        score = 0
        if d.seam_name and d.seam_name.lower() in ev:
            score += 3
        if re.search(r"thickness\s+of\s+(?:the\s+)?seam", ev):
            score += 4
        if "varies" in ev or "varying" in ev:
            score += 2
        if "parting" in ev:
            score -= 5
        if d.seam_name:
            score += 1
        return score

    for _key, group in range_groups.items():
        best = max(group, key=_range_score)
        if _range_score(best) >= 0:
            kept.append(best)
    drafts = kept

    # ── Pass 2: "thickness of the seam X …" point/range already handled; point measures ──
    for m in _SEAM_OF_THICKNESS_RE.finditer(text):
        seam = _normalize_seam_label(m.group(1))
        if not seam:
            continue
        # Local window after the seam mention for a point thickness if not already a range
        window = text[m.start() : min(len(text), m.end() + 220)]
        # Skip if this region already contributed a range fact for this seam
        if any(
            d.seam_name == seam and d.thickness_min and d.source_page == page_number
            for d in drafts
        ):
            continue
        tm = _THICKNESS_POINT_RE.search(window)
        if not tm:
            # Still record the seam mention alone
            draft = GeologicalFactDraft(
                seam_name=seam,
                source_page=page_number,
                source_location=_loc(),
                evidence_text=_evidence_window(text, m.start(), m.end()),
            )
            done = _finalize(draft)
            if done:
                drafts.append(done)
            continue
        abs_start = m.start() + tm.start()
        span = (abs_start, m.start() + tm.end())
        if span in used_spans:
            continue
        used_spans.add(span)
        draft = GeologicalFactDraft(
            seam_name=seam,
            source_page=page_number,
            source_location=_loc(),
            evidence_text=_evidence_window(text, abs_start, m.start() + tm.end()),
        )
        _attach_length(draft, kind="thickness", value_raw=tm.group(1), unit_raw=tm.group(2))
        bh = _find_borehole_near(text, abs_start)
        if bh:
            draft.borehole_id = bh
        done = _finalize(draft)
        if done:
            drafts.append(done)

    # ── Pass 3: borehole / seam anchors with local measures (legacy path, improved) ──
    anchors: list[tuple[str, str, int, int]] = []
    for m in _BH_RE.finditer(text):
        anchors.append(("borehole", m.group(1).upper(), m.start(), m.end()))
    for m in _SEAM_QUALIFIED_RE.finditer(text):
        seam = _normalize_seam_label(m.group(1))
        if seam:
            anchors.append(("seam", seam, m.start(), m.end()))
    for m in _SEAM_CODE_BEFORE_RE.finditer(text):
        seam = _normalize_seam_label(m.group(1))
        if seam:
            anchors.append(("seam", seam, m.start(), m.end()))

    if not anchors and not drafts:
        anchors.append(("none", "", 0, 0))

    for kind, value, a0, a1 in anchors:
        draft = GeologicalFactDraft(
            source_page=page_number,
            source_location=_loc(),
            evidence_text=_evidence_window(text, a0, a1),
        )
        if kind == "borehole":
            draft.borehole_id = value
        elif kind == "seam":
            draft.seam_name = value

        window = text[max(0, a0 - 120) : min(len(text), a1 + 240)] if kind != "none" else text

        # Prefer range inside window if not already captured
        rm = _THICKNESS_RANGE_RE.search(window)
        if rm and kind in {"seam", "borehole"}:
            # Only attach if this seam/bh not already has a range on this page
            already = any(
                d.thickness_min
                and d.source_page == page_number
                and (
                    (kind == "seam" and d.seam_name == value)
                    or (kind == "borehole" and d.borehole_id == value)
                )
                for d in drafts
            )
            if not already:
                # Absolute position of the range in the full page text
                abs_rm_start = max(0, a0 - 120) + rm.start()
                abs_rm_end = max(0, a0 - 120) + rm.end()
                natural_seam = _find_seam_near(text, abs_rm_end)
                # Do not steal another seam's narrative thickness range
                if kind == "seam" and natural_seam and natural_seam != value:
                    continue
                unit = rm.group(2) or rm.group(4) or "m"
                _attach_thickness_range(
                    draft, min_raw=rm.group(1), max_raw=rm.group(3), unit_raw=unit
                )
                draft.evidence_text = _evidence_window(
                    text, abs_rm_start, abs_rm_end, radius=140
                )
                # Block-level general ranges are not borehole-specific
                if re.search(
                    r"(?i)(?:varies?|varying)\s+within\s+the\s+block|general\s+thickness",
                    draft.evidence_text or "",
                ):
                    if kind == "borehole":
                        continue  # don't re-emit block range under a borehole anchor
                    draft.borehole_id = None
                elif kind == "borehole" and not draft.seam_name:
                    draft.seam_name = natural_seam or _find_seam_near(text, a0)
                if kind == "seam" and not draft.borehole_id:
                    if not re.search(
                        r"(?i)(?:varies?|varying)\s+within\s+the\s+block|general\s+thickness",
                        draft.evidence_text or "",
                    ):
                        draft.borehole_id = _find_borehole_near(text, abs_rm_end)
                done = _finalize(draft)
                if done:
                    drafts.append(done)
                continue

        dm = _DEPTH_RE.search(window)
        if dm:
            span = (max(0, a0 - 120) + dm.start(), max(0, a0 - 120) + dm.end())
            if span not in used_spans:
                _attach_length(draft, kind="depth", value_raw=dm.group(1), unit_raw=dm.group(2))
                used_spans.add(span)
                draft.evidence_text = _evidence_window(window, dm.start(), dm.end())

        tm = _THICKNESS_POINT_RE.search(window)
        if tm and not draft.thickness_min:
            span = (max(0, a0 - 120) + tm.start(), max(0, a0 - 120) + tm.end())
            if span not in used_spans:
                # Minimum workable thickness is not a named-seam thickness
                tm_ctx = window[max(0, tm.start() - 40) : tm.end() + 20]
                if re.search(r"(?i)\bworkable\b", tm_ctx) or re.search(
                    r"(?i)\bminimum\s+thickness\b", tm_ctx
                ):
                    if kind == "seam":
                        continue  # do not attach workable norms to a named seam
                    # Emit as workable metric instead (handled in dedicated pass when possible)
                    continue
                _attach_length(draft, kind="thickness", value_raw=tm.group(1), unit_raw=tm.group(2))
                used_spans.add(span)
                if not draft.evidence_text or len(draft.evidence_text) < 20:
                    draft.evidence_text = _evidence_window(window, tm.start(), tm.end())
                # Associate missing seam for borehole-anchored thickness
                if kind == "borehole" and not draft.seam_name:
                    draft.seam_name = _find_seam_near(text, a0)
                if kind == "seam" and not draft.borehole_id:
                    draft.borehole_id = _find_borehole_near(text, a0)
                # Cross-link when both appear in the same short window
                if draft.thickness and not draft.borehole_id:
                    draft.borehole_id = _find_borehole_near(text, a0)
                if draft.thickness and not draft.seam_name:
                    draft.seam_name = _find_seam_near(text, a0)
                if draft.seam_name:
                    draft.seam_status = "named"
                    draft.metric_kind = draft.metric_kind or "seam_thickness"

        low = window.lower()
        labeled = re.search(
            r"(?i)\blithology\s*[:=\-]\s*([A-Za-z][A-Za-z\s-]{1,40})",
            window,
        )
        if labeled:
            candidate = labeled.group(1).strip().split("\n")[0].strip(" .,;")
            found = None
            for term in sorted(LITHOLOGY_TERMS, key=len, reverse=True):
                if re.search(rf"(?i)^(?:{re.escape(term)})\b", candidate):
                    found = term
                    break
            if found:
                draft.lithology = "Coal" if found == "coal" else found.title()
            else:
                first = candidate.split()[0]
                if first.lower() in LITHOLOGY_TERMS:
                    draft.lithology = "Coal" if first.lower() == "coal" else first.title()
        if not draft.lithology:
            earliest = None
            for term in LITHOLOGY_TERMS:
                mm = re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", low)
                if mm and (earliest is None or mm.start() < earliest[0]):
                    earliest = (mm.start(), term)
            if earliest:
                term = earliest[1]
                draft.lithology = "Coal" if term == "coal" else term.title()

        fm = _FORMATION_RE.search(window)
        if fm:
            draft.geological_formation = _safe_formation_name(
                _formation_raw_from_match(fm), context=window
            )

        sm = _STRUCTURE_RE.search(window)
        if sm:
            draft.geological_structure = sm.group(1).lower()

        for phrase, label in COAL_QUALITY_PARAMS:
            qm = re.search(
                rf"(?i)\b{re.escape(phrase)}\s*(?:content|value)?\s*(?:of|:)?\s*"
                rf"([+-]?\d+(?:[.,]\d+)?)\s*([A-Za-z/%°]+)?",
                window,
            )
            if qm:
                draft.coal_quality_parameter = label
                draft.coal_quality_value = qm.group(1).replace(",", "")
                draft.coal_quality_unit = qm.group(2)
                break

        done = _finalize(draft)
        if done:
            # Deduplicate against earlier range facts for same seam+page
            if done.thickness_min and done.seam_name:
                if any(
                    d.seam_name == done.seam_name
                    and d.thickness_min == done.thickness_min
                    and d.source_page == page_number
                    for d in drafts
                ):
                    continue
            drafts.append(done)

    # ── Pass: coal resource / reserve quantities (generic; no hard-coded values) ──
    _RESOURCE_RE = re.compile(
        r"(?i)(?:(?:gross\s+)?(?:inferred|indicated|measured|total)\s+"
        r"(?:coal\s+)?resources?\b|"
        r"contributes\s+\d+\.\d+\s*MT\s+of\s+(?:gross\s+)?(?:inferred\s+)?(?:coal\s+)?resource|"
        r"(?:gross\s+)?inferred\s+coal\s+resource)"
        r"[^.\n]{0,160}?"
        r"(\d+\.\d+)\s*(MT|Mt|mt|million\s*tonnes?)?"
    )
    _RESERVE_RE = re.compile(
        r"(?i)(?:(?:inferred|indicated|measured|proved|probable)\s+"
        r"(?:coal\s+)?reserves?\b)"
        r"[^.\n]{0,160}?"
        r"(\d+\.\d+)\s*(MT|Mt|mt|million\s*tonnes?)?"
    )
    for kind, cre in (("resource", _RESOURCE_RE), ("reserve", _RESERVE_RE)):
        for m in cre.finditer(text):
            ev = _evidence_window(text, m.start(), m.end(), radius=160)
            # Prefer the MT quantity nearest the cue; fall back to capture group
            mq = re.search(r"(?i)(\d+\.\d+)\s*(MT|Mt|mt)\b", ev)
            num = (mq.group(1) if mq else m.group(1)).replace(",", "")
            unit = (mq.group(2) if mq else (m.group(2) or "MT")) or "MT"
            try:
                if float(num) <= 0 or float(num) > 1e6:
                    continue
            except ValueError:
                continue
            seam = _find_seam_near(text, m.start()) or _find_seam_near(text, m.end())
            draft = GeologicalFactDraft(
                source_page=page_number,
                source_location=_loc(),
                evidence_text=ev,
                seam_name=seam,
                seam_status="named" if seam else None,
                metric_kind=kind,
                original_value=num,
                original_unit=unit,
            )
            # Stash quantity in original_* ; display via _fact_value / original_value
            done = _finalize(draft)
            if done:
                drafts.append(done)

    # ── Pass: named geological formations (listing entities; reject grammar fragments) ──
    seen_fm_keys: set[str] = set()
    for m in _FORMATION_RE.finditer(text):
        ev = _evidence_window(text, m.start(), m.end(), radius=100)
        safe_fm = _safe_formation_name(_formation_raw_from_match(m), context=ev)
        if not safe_fm:
            continue
        from app.geology.entities import formation_match_key

        key = formation_match_key(safe_fm)
        if not key or key in seen_fm_keys:
            continue
        # Skip if already emitted as formation_thickness for same name on this page
        if any(
            (d.geological_formation and formation_match_key(d.geological_formation) == key)
            and (d.metric_kind or "") in {"formation", "formation_thickness"}
            for d in drafts
        ):
            seen_fm_keys.add(key)
            continue
        seen_fm_keys.add(key)
        draft = GeologicalFactDraft(
            source_page=page_number,
            source_location=_loc(),
            evidence_text=ev,
            geological_formation=safe_fm,
            metric_kind="formation",
        )
        done = _finalize(draft)
        if done:
            drafts.append(done)

    return drafts


def extract_facts_from_pages(
    pages: list[tuple[int, str, Optional[str]]],
) -> list[GeologicalFactDraft]:
    """pages: list of (page_number, text, source_location)."""
    out: list[GeologicalFactDraft] = []
    for page_number, text, loc in pages:
        out.extend(
            extract_facts_from_page(
                text,
                page_number=page_number,
                source_location=loc,
            )
        )
    return out
