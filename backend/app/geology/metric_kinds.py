"""Geological metric kinds — distinguish seam vs formation vs parting thickness, etc.

Generic classifiers only: no document names, page numbers, or hard-coded answers.
"""

from __future__ import annotations

import re
from typing import Optional

# Canonical geological metrics used by routing + retrieval filters
SEAM_THICKNESS = "seam_thickness"
FORMATION_THICKNESS = "formation_thickness"
SEAM_PARTING_THICKNESS = "seam_parting_thickness"
SEAM_DEPTH = "seam_depth"
BOREHOLE_DEPTH = "borehole_depth"
OVERBURDEN_THICKNESS = "overburden_thickness"
MINIMUM_WORKABLE_SEAM_THICKNESS = "minimum_workable_seam_thickness"
STRATIGRAPHIC_DEPTH = "stratigraphic_depth"
COAL_QUALITY = "coal_quality"
RESOURCE_QUANTITY = "resource_quantity"
RESERVE_QUANTITY = "reserve_quantity"
SEAM = "seam"
BOREHOLE = "borehole"
LITHOLOGY = "lithology"
FORMATION = "formation"
GEOLOGICAL_STRUCTURE = "geological_structure"

THICKNESS_METRICS = {
    SEAM_THICKNESS,
    FORMATION_THICKNESS,
    SEAM_PARTING_THICKNESS,
    OVERBURDEN_THICKNESS,
    MINIMUM_WORKABLE_SEAM_THICKNESS,
}

# Mutual exclusions: requesting A must not be satisfied by evidence of kind B
METRIC_INCOMPATIBLE: dict[str, frozenset[str]] = {
    SEAM_THICKNESS: frozenset(
        {
            FORMATION_THICKNESS,
            SEAM_PARTING_THICKNESS,
            OVERBURDEN_THICKNESS,
            MINIMUM_WORKABLE_SEAM_THICKNESS,
            BOREHOLE_DEPTH,
            STRATIGRAPHIC_DEPTH,
            SEAM_DEPTH,
            RESOURCE_QUANTITY,
            RESERVE_QUANTITY,
        }
    ),
    FORMATION_THICKNESS: frozenset(
        {
            SEAM_THICKNESS,
            SEAM_PARTING_THICKNESS,
            OVERBURDEN_THICKNESS,
            MINIMUM_WORKABLE_SEAM_THICKNESS,
            BOREHOLE_DEPTH,
            SEAM_DEPTH,
        }
    ),
    SEAM_PARTING_THICKNESS: frozenset(
        {
            SEAM_THICKNESS,
            FORMATION_THICKNESS,
            OVERBURDEN_THICKNESS,
            MINIMUM_WORKABLE_SEAM_THICKNESS,
            BOREHOLE_DEPTH,
        }
    ),
    MINIMUM_WORKABLE_SEAM_THICKNESS: frozenset(
        {
            SEAM_THICKNESS,
            FORMATION_THICKNESS,
            SEAM_PARTING_THICKNESS,
            OVERBURDEN_THICKNESS,
            BOREHOLE_DEPTH,
        }
    ),
    SEAM_DEPTH: frozenset({SEAM_THICKNESS, FORMATION_THICKNESS, BOREHOLE_DEPTH}),
    BOREHOLE_DEPTH: frozenset({SEAM_THICKNESS, FORMATION_THICKNESS, SEAM_DEPTH}),
}


_FORMATION_THICKNESS_RE = re.compile(
    r"(?i)\b(?:thickness|thick)\b.{0,40}\bformation\b"
    r"|\bformation\b.{0,60}\b(?:thickness|thick)\b"
    r"|\baverage\s+thickness\s+of\s+(?:the\s+)?\w+\s+formation\b"
)

_PARTING_THICKNESS_RE = re.compile(
    r"(?i)\b(?:thickness\s+of\s+(?:the\s+)?parting|parting\s+thickness|"
    r"thickness\s+of\s+parting|THICKNESS\s+OF\s+PARTING)\b"
)

_OVERBURDEN_RE = re.compile(r"(?i)\boverburden\b.{0,40}\b(?:thickness|thick)\b|\bthickness\b.{0,40}\boverburden\b")

_WORKABLE_THICKNESS_RE = re.compile(
    r"(?i)\b(?:minimum\s+workable\s+thickness|workable\s+thickness|"
    r"minimum\s+thickness\s+(?:has\s+been\s+)?considered|"
    r"min(?:imum)?\s+workable)\b"
)

_SEAM_THICKNESS_RE = re.compile(
    r"(?i)\b(?:seam\s+thickness|thickness\s+of\s+(?:the\s+)?(?:coal\s+)?seams?"
    r"|general\s+thickness.{0,40}seam|thickness\s+of\s+(?:the\s+)?seam\s+)"
)

# Methodology / cut-off / dirt-band thickness — never seam_thickness of a named seam
_METHODOLOGY_THICKNESS_RE = re.compile(
    r"(?i)\b(?:below\s+\d+(?:[.,]\d+)?\s*(?:cm|mm|m)\s+thickness|"
    r"\d+(?:[.,]\d+)?\s*(?:cm|mm|m)\s+thickness\s+and\s+excluding|"
    r"non[- ]?combustible\s+bands?|"
    r"dirt\s*bands?\b.{0,40}\bthickness|"
    r"thickness\b.{0,40}\bdirt\s*bands?|"
    r"combustible\s+bands?\s+below|"
    r"discarded|discarding)\b"
)

_BOREHOLE_DEPTH_RE = re.compile(
    r"(?i)\b(?:depth\s+of\s+(?:the\s+)?borehole|borehole\s+depth|"
    r"how\s+deep\s+(?:was|is)\s+(?:the\s+)?borehole|drilled\s+to\s+a\s+depth)\b"
)


def classify_query_thickness_metric(question: str) -> Optional[str]:
    """Resolve which thickness/depth metric a question asks for (subject-aware)."""
    q = question or ""
    low = q.lower()

    if _WORKABLE_THICKNESS_RE.search(q) or (
        re.search(r"(?i)\bworkable\b", low) and re.search(r"(?i)\bthickness|thick\b", low)
    ):
        return MINIMUM_WORKABLE_SEAM_THICKNESS

    if _PARTING_THICKNESS_RE.search(q) or re.search(r"(?i)\bparting\b", low) and re.search(
        r"(?i)\bthickness|thick\b", low
    ):
        return SEAM_PARTING_THICKNESS

    if _OVERBURDEN_RE.search(q):
        return OVERBURDEN_THICKNESS

    if re.search(r"(?i)\bformation\b", low) and re.search(r"(?i)\bthickness|thick|how\s+thick\b", low):
        # "thickness of the Barakar Formation" / "how thick is the formation"
        if not re.search(r"(?i)\bseams?\b", low):
            return FORMATION_THICKNESS

    if _BOREHOLE_DEPTH_RE.search(q) or (
        re.search(r"(?i)\bborehole\b", low) and re.search(r"(?i)\b(?:depth|deep|how\s+deep)\b", low)
    ):
        return BOREHOLE_DEPTH

    if re.search(r"(?i)\b(?:depth|how\s+deep)\b", low) and re.search(r"(?i)\bseams?\b", low):
        return SEAM_DEPTH

    if re.search(r"(?i)\bthickness|thick|how\s+thick\b", low):
        if re.search(r"(?i)\bseams?\b|\bcoal\s+seams?\b", low):
            return SEAM_THICKNESS
        # "How thick is Seam IV?" — seam name present via "seam"
        if re.search(r"(?i)\bseam\s+[a-z0-9]", low):
            return SEAM_THICKNESS

    return None


def _has_thickness_measure(text: str) -> bool:
    """True when text states a thickness with an explicit numeric measure + unit."""
    return bool(
        re.search(
            r"(?i)\bthickness\b.{0,80}?\d+(?:[.,]\d+)?\s*(?:m|meter|meters|metre|metres|cm|mm|ft|feet|foot)\b"
            r"|\b\d+(?:[.,]\d+)?\s*(?:m|meter|meters|metre|metres|cm|mm|ft|feet|foot)\b.{0,60}?\bthickness\b"
            r"|\b(?:varies?|varying|ranging|from|between)\s+(?:from\s+|between\s+)?"
            r"\d+(?:[.,]\d+)?\s*(?:m|meter|metres|cm|mm)?\s*(?:to|[-–—]|and)\s*"
            r"\d+(?:[.,]\d+)?\s*(?:m|meter|metres|cm|mm)?",
            text or "",
        )
    )


def classify_evidence_metric_kind(
    *,
    text: Optional[str] = None,
    seam_name: Optional[str] = None,
    borehole_id: Optional[str] = None,
    geological_formation: Optional[str] = None,
    has_thickness: bool = False,
    has_depth: bool = False,
    requested: Optional[str] = None,
) -> Optional[str]:
    """Infer the metric kind of a fact/excerpt from its geological context."""
    ev = text or ""
    low = ev.lower()
    thickness_measure = has_thickness or _has_thickness_measure(ev)

    if _PARTING_THICKNESS_RE.search(ev) or (
        "parting" in low and thickness_measure and not seam_name
    ):
        return SEAM_PARTING_THICKNESS

    if _WORKABLE_THICKNESS_RE.search(ev) or (
        "workable" in low and "thickness" in low and thickness_measure
    ):
        return MINIMUM_WORKABLE_SEAM_THICKNESS

    if _OVERBURDEN_RE.search(ev):
        return OVERBURDEN_THICKNESS

    # Dirt-band / combustible-band cut-off methodology is not named-seam thickness
    if _METHODOLOGY_THICKNESS_RE.search(ev) and not _SEAM_THICKNESS_RE.search(ev):
        if requested == SEAM_THICKNESS:
            return None
        # Leave unclassified unless another cue wins below
        if not seam_name:
            return None

    if thickness_measure or re.search(r"(?i)\bthickness|thick\b", low):
        # Formation thickness: formation subject, no seam association
        if (
            geological_formation
            or _FORMATION_THICKNESS_RE.search(ev)
            or (
                re.search(r"(?i)\b\w+\s+formation\b", low)
                and _has_thickness_measure(ev)
            )
        ) and not seam_name:
            if not re.search(r"(?i)\bthickness\s+of\s+(?:the\s+)?seam\b", low):
                if _has_thickness_measure(ev) or geological_formation:
                    return FORMATION_THICKNESS
        # Seam thickness requires seam context AND a real thickness measure.
        # Do not treat bare co-occurrence of "seam" + "thickness" on a long page
        # as seam_thickness when methodology/dirt-band cues dominate.
        if _METHODOLOGY_THICKNESS_RE.search(ev) and not _SEAM_THICKNESS_RE.search(ev):
            if requested == SEAM_THICKNESS:
                return None
        if _has_thickness_measure(ev) and (
            seam_name or _SEAM_THICKNESS_RE.search(ev)
        ):
            if not re.search(r"(?i)\bformation\b", low) or seam_name:
                return SEAM_THICKNESS
        # Explicit "seam thickness" phrasing without dirt-band methodology
        if (
            _has_thickness_measure(ev)
            and _SEAM_THICKNESS_RE.search(ev)
            and not _METHODOLOGY_THICKNESS_RE.search(ev)
        ):
            return SEAM_THICKNESS
        # Ambiguous thickness — do not claim seam_thickness without measure
        if requested == SEAM_THICKNESS:
            return None
        if geological_formation and _has_thickness_measure(ev):
            return FORMATION_THICKNESS

    if has_depth or re.search(r"(?i)\bdepth\b", low):
        if borehole_id or re.search(r"(?i)\bborehole\b", low):
            return BOREHOLE_DEPTH
        if seam_name or re.search(r"(?i)\bseam\b", low):
            return SEAM_DEPTH
        return STRATIGRAPHIC_DEPTH

    return None


def metrics_compatible(requested: Optional[str], evidence_kind: Optional[str]) -> bool:
    """True when evidence_kind may satisfy requested metric."""
    if not requested:
        return True
    if not evidence_kind:
        # Unknown evidence kind: only allow for non-thickness listing metrics
        if requested in THICKNESS_METRICS or requested in {
            SEAM_DEPTH,
            BOREHOLE_DEPTH,
            STRATIGRAPHIC_DEPTH,
        }:
            return False
        return True
    if evidence_kind == requested:
        return True
    blocked = METRIC_INCOMPATIBLE.get(requested, frozenset())
    if evidence_kind in blocked:
        return False
    # Listing metrics (seam, borehole) are not thickness substitutes
    if requested in THICKNESS_METRICS and evidence_kind not in THICKNESS_METRICS:
        return False
    if requested == SEAM and evidence_kind in THICKNESS_METRICS:
        # Thickness facts may still carry a seam name for listing — allow if same family
        return evidence_kind == SEAM_THICKNESS
    # Resource/reserve quantities are often attached to seam-associated rows
    if requested in {
        "resource",
        "reserve",
        "resource_quantity",
        "reserve_quantity",
    } and evidence_kind in {
        "resource",
        "reserve",
        "resource_quantity",
        "reserve_quantity",
        "seam",
    }:
        return True
    if evidence_kind in {
        "resource",
        "reserve",
        "resource_quantity",
        "reserve_quantity",
    } and requested == SEAM:
        # Resource facts may surface a seam name during seam listing
        return True
    return False

def formation_thickness_pattern(text: str) -> bool:
    return bool(_FORMATION_THICKNESS_RE.search(text or ""))
