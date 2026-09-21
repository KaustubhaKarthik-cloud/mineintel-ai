"""Geological domain taxonomy and keyword cues (config-driven, not filename hacks)."""

from __future__ import annotations

from enum import Enum


class DocumentDomain(str, Enum):
    GEOLOGICAL_EXPLORATION = "geological_exploration"
    MINING_PRODUCTION = "mining_production"
    ENVIRONMENTAL = "environmental"
    PROJECT_TECHNICAL = "project_technical"
    OTHER = "other"


DOMAIN_LABELS: dict[str, str] = {
    DocumentDomain.GEOLOGICAL_EXPLORATION.value: "GEOLOGICAL / EXPLORATION",
    DocumentDomain.MINING_PRODUCTION.value: "MINING / PRODUCTION",
    DocumentDomain.ENVIRONMENTAL.value: "ENVIRONMENTAL",
    DocumentDomain.PROJECT_TECHNICAL.value: "PROJECT / TECHNICAL",
    DocumentDomain.OTHER.value: "OTHER",
}

# Weighted keyword / phrase cues. Higher weight = stronger domain signal.
# Generic terms only — never tied to specific filenames or company names.
DOMAIN_CUES: dict[str, list[tuple[str, float]]] = {
    DocumentDomain.GEOLOGICAL_EXPLORATION.value: [
        ("borehole", 3.0),
        ("bore hole", 3.0),
        ("drilling", 2.5),
        ("drill hole", 2.5),
        ("coal seam", 3.0),
        ("seam thickness", 3.0),
        ("seam depth", 3.0),
        ("lithology", 3.0),
        ("sandstone", 2.0),
        ("shale", 2.0),
        ("geological formation", 3.0),
        ("formation", 1.5),
        ("fault", 2.0),
        ("exploration", 2.0),
        ("geological section", 2.5),
        ("stratigraphy", 3.0),
        ("coal quality", 2.5),
        ("resource", 1.2),
        ("reserve", 1.2),
        ("core log", 2.5),
        ("lithological", 2.5),
        ("overburden rock", 1.5),
        ("geological report", 2.5),
        ("seam ", 1.8),
    ],
    DocumentDomain.MINING_PRODUCTION.value: [
        ("production", 2.5),
        ("offtake", 2.5),
        ("dispatch", 2.0),
        ("overburden removal", 2.0),
        ("achievement", 2.0),
        ("target", 1.5),
        ("mt", 1.0),
        ("million tonnes", 2.0),
        ("coal production", 3.0),
        ("monthly return", 2.0),
        ("subsidiary", 1.2),
        ("oc production", 2.0),
        ("ug production", 2.0),
    ],
    DocumentDomain.ENVIRONMENTAL.value: [
        ("environmental", 3.0),
        ("emission", 2.5),
        ("afforestation", 2.5),
        ("reclamation", 2.0),
        ("water quality", 2.5),
        ("air quality", 2.5),
        ("effluent", 2.5),
        ("cpm", 1.5),
        ("green belt", 2.0),
        ("pollution", 2.5),
        ("compliance", 1.5),
    ],
    DocumentDomain.PROJECT_TECHNICAL.value: [
        ("feasibility", 2.5),
        ("dpr", 2.0),
        ("detailed project report", 3.0),
        ("technical specification", 2.5),
        ("engineering design", 2.5),
        ("project report", 2.0),
        ("tender", 1.5),
        ("scope of work", 2.0),
        ("bill of quantities", 2.0),
    ],
}

# Canonical lithology tokens for extraction (matched only when present in evidence)
LITHOLOGY_TERMS = (
    "coal",
    "sandstone",
    "shale",
    "claystone",
    "siltstone",
    "limestone",
    "mudstone",
    "carbonaceous shale",
    "fireclay",
    "conglomerate",
)

COAL_QUALITY_PARAMS = (
    ("gcv", "GCV"),
    ("gross calorific value", "GCV"),
    ("ash", "Ash"),
    ("moisture", "Moisture"),
    ("volatile matter", "Volatile Matter"),
    ("fixed carbon", "Fixed Carbon"),
    ("sulphur", "Sulphur"),
    ("sulfur", "Sulphur"),
)
