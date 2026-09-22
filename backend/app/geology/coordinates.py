"""Document-grounded geological coordinates — never invent or geocode.

Only accepts explicit latitude/longitude found in GeologicalFact structured
fields (meta) or tightly controlled evidence patterns. No mine-name geocoding,
no defaults, no user location, no country fallbacks.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.geology.explorer import REJECTED_STATUS, _doc_map, _doc_meta
from app.models import Document, GeologicalFact

LOCATION_UNAVAILABLE = "Location unavailable from verified document data."

# Explicit coordinate patterns only (not place names, not bare number pairs).
# REQUIRE either labeled latitude/longitude OR hemisphere letters (N/S + E/W).
_LAT_LON_LABELED_PAIR_RE = re.compile(
    r"(?i)\blat(?:itude)?\s*[=:]?\s*"
    r"([+-]?\d{1,2}(?:\.\d+)?)\s*°?\s*([nNsS])?"
    r"\s*[,;/]\s*"
    r"lon(?:g(?:itude)?)?\s*[=:]?\s*"
    r"([+-]?\d{1,3}(?:\.\d+)?)\s*°?\s*([eEwW])?\b"
)

_LAT_LON_HEMISPHERE_PAIR_RE = re.compile(
    r"(?i)\b"
    r"([+-]?\d{1,2}(?:\.\d+)?)\s*°?\s*([nNsS])"
    r"\s*[,;/]\s*"
    r"([+-]?\d{1,3}(?:\.\d+)?)\s*°?\s*([eEwW])\b"
)

_LABELED_LAT_RE = re.compile(
    r"(?i)\blatitude\s*[=:]\s*([+-]?\d{1,2}(?:\.\d+)?)\s*°?\s*([nNsS])?\b"
)
_LABELED_LON_RE = re.compile(
    r"(?i)\blongitude\s*[=:]\s*([+-]?\d{1,3}(?:\.\d+)?)\s*°?\s*([eEwW])?\b"
)


def _signed(value: float, hemi: Optional[str], *, positive: str, negative: str) -> Optional[float]:
    h = (hemi or "").upper()
    if h == negative:
        value = -abs(value)
    elif h == positive:
        value = abs(value)
    return value


def parse_coordinates_from_text(text: Optional[str]) -> Optional[tuple[float, float]]:
    """Parse explicit lat/lon from text. Returns None if not safely parseable."""
    if not text:
        return None

    m = _LAT_LON_LABELED_PAIR_RE.search(text) or _LAT_LON_HEMISPHERE_PAIR_RE.search(text)
    if m:
        try:
            lat = float(m.group(1))
            lon = float(m.group(3))
        except ValueError:
            return None
        lat = _signed(lat, m.group(2), positive="N", negative="S")
        lon = _signed(lon, m.group(4), positive="E", negative="W")
        if lat is None or lon is None:
            return None
        if abs(lat) <= 90 and abs(lon) <= 180:
            return lat, lon
        return None

    ml = _LABELED_LAT_RE.search(text)
    mn = _LABELED_LON_RE.search(text)
    if ml and mn:
        try:
            lat = float(ml.group(1))
            lon = float(mn.group(1))
        except ValueError:
            return None
        lat = _signed(lat, ml.group(2), positive="N", negative="S")
        lon = _signed(lon, mn.group(2), positive="E", negative="W")
        if lat is None or lon is None:
            return None
        if abs(lat) <= 90 and abs(lon) <= 180:
            return lat, lon
    return None


def parse_coordinates_from_meta(meta: Optional[dict]) -> Optional[tuple[float, float]]:
    """Read verified lat/lon from fact/document meta when explicitly stored."""
    if not isinstance(meta, dict):
        return None
    for key_lat, key_lon in (
        ("latitude", "longitude"),
        ("lat", "lon"),
        ("lat", "lng"),
    ):
        if key_lat in meta and key_lon in meta:
            try:
                lat = float(meta[key_lat])
                lon = float(meta[key_lon])
            except (TypeError, ValueError):
                continue
            if abs(lat) <= 90 and abs(lon) <= 180:
                return lat, lon
    coords = meta.get("coordinates")
    if isinstance(coords, dict):
        return parse_coordinates_from_meta(coords)
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            lat, lon = float(coords[0]), float(coords[1])
        except (TypeError, ValueError):
            return None
        if abs(lat) <= 90 and abs(lon) <= 180:
            return lat, lon
    return None


def _coords_for_fact(row: GeologicalFact) -> Optional[tuple[float, float, str]]:
    """Return (lat, lon, source) or None."""
    meta_coords = parse_coordinates_from_meta(row.meta if isinstance(row.meta, dict) else None)
    if meta_coords:
        return meta_coords[0], meta_coords[1], "geological_fact.meta"
    text_coords = parse_coordinates_from_text(row.evidence_text)
    if text_coords:
        return text_coords[0], text_coords[1], "geological_fact.evidence_text"
    return None


def list_document_locations(
    db: Session,
    *,
    document_id: Optional[str] = None,
) -> dict[str, Any]:
    """Locations grounded only in verified explicit coordinates."""
    q = db.query(GeologicalFact).filter(GeologicalFact.status != REJECTED_STATUS)
    if document_id:
        q = q.filter(GeologicalFact.document_id == document_id)
    rows = q.limit(8000).all()

    by_doc: dict[str, dict[str, Any]] = {}
    for row in rows:
        parsed = _coords_for_fact(row)
        if not parsed:
            continue
        lat, lon, source = parsed
        entry = by_doc.get(row.document_id)
        if entry:
            continue  # keep first verified coordinate per document
        by_doc[row.document_id] = {
            "document_id": row.document_id,
            "latitude": lat,
            "longitude": lon,
            "location_source": source,
            "fact_id": row.id,
            "page": row.source_page,
            "evidence_text": row.evidence_text,
            "status": row.status,
            "metric_kind": row.metric_kind,
        }

    # Also check Document.meta for explicit trusted coordinates
    doc_q = db.query(Document)
    if document_id:
        doc_q = doc_q.filter(Document.id == document_id)
    docs = {d.id: d for d in doc_q.all()}
    for did, doc in docs.items():
        if did in by_doc:
            continue
        meta = doc.meta if isinstance(doc.meta, dict) else {}
        parsed = parse_coordinates_from_meta(meta.get("coordinates") if isinstance(meta.get("coordinates"), dict) else meta)
        if not parsed:
            continue
        by_doc[did] = {
            "document_id": did,
            "latitude": parsed[0],
            "longitude": parsed[1],
            "location_source": "document.meta",
            "fact_id": None,
            "page": None,
            "evidence_text": None,
            "status": "verified_metadata",
            "metric_kind": None,
        }

    items = []
    doc_map = _doc_map(db, set(by_doc.keys()) | ({document_id} if document_id else set()))
    for did, loc in by_doc.items():
        meta = _doc_meta(doc_map.get(did))
        items.append({**loc, "document_name": meta.get("document_name")})

    items.sort(key=lambda x: (x.get("document_name") or "").lower())

    if document_id and not items:
        doc = docs.get(document_id) or db.get(Document, document_id)
        meta = _doc_meta(doc)
        return {
            "available": False,
            "message": LOCATION_UNAVAILABLE,
            "items": [],
            "document": meta,
        }

    return {
        "available": bool(items),
        "message": None if items else LOCATION_UNAVAILABLE,
        "items": items,
        "count": len(items),
    }
