"""Extensible mining topic cues — linguistic patterns, not org/document maps."""

from __future__ import annotations

# Canonical topic → keyword cues (case-insensitive substring match).
# New documents can still surface these topics; unknown themes can be added later
# without hard-coding company or filename special cases.
TOPIC_CUES: dict[str, tuple[str, ...]] = {
    "Production": (
        "production",
        "produced",
        "output",
        "tonnage",
        "production performance",
    ),
    "Exploration": (
        "exploration",
        "prospecting",
        "drilling programme",
        "drilling program",
        "reserve estimation",
    ),
    "Geology": (
        "geology",
        "geological",
        "lithology",
        "strata",
        "seam",
        "ore body",
        "orebody",
    ),
    "Mining Operations": (
        "mining operations",
        "opencast",
        "open cast",
        "underground",
        "excavation",
        "blasting",
        "haulage",
    ),
    "Overburden": (
        "overburden",
        "ob removal",
        "over burden",
        "stripping",
    ),
    "Coal and Lignite": (
        "lignite",
        "coal production",
        "coal mine",
        "coking coal",
        "thermal coal",
    ),
    "Safety": (
        "safety",
        "accident",
        "incident",
        "fatality",
        "mine safety",
        "occupational health",
    ),
    "Environment": (
        "environment",
        "environmental",
        "emission",
        "afforestation",
        "water quality",
        "air quality",
        "pollution",
    ),
    "Infrastructure": (
        "infrastructure",
        "conveyor",
        "railway siding",
        "power plant",
        "washery",
        "workshop",
    ),
    "Equipment": (
        "equipment",
        "excavator",
        "dumpers",
        "shovel",
        "dragline",
        "machinery",
    ),
    "Rehabilitation": (
        "rehabilitation",
        "reclamation",
        "backfilling",
        "mine closure",
        "land restoration",
    ),
    "Financial and Operational Performance": (
        "financial",
        "revenue",
        "profit",
        "operational performance",
        "turnover",
        "ebitda",
    ),
    "Targets and Achievements": (
        "target",
        "achievement",
        "against the target",
        "capacity utilisation",
        "capacity utilization",
    ),
}


def slugify(name: str) -> str:
    import re

    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "topic"
