"""Optional Paddle document/table assist — never replaces structured_table.

Primary table extraction remains:
  app.retrieval.structured_table (PyMuPDF find_tables + header-first binding)

This module may attach supplemental OCR table hints to page content_meta when
OCR_TABLE_ENGINE=paddle and PaddleOCR structure APIs are available. On any
failure, callers keep the existing extractor path unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)


def paddle_table_assist_enabled() -> bool:
    settings = get_settings()
    eng = (settings.ocr_table_engine or "existing").strip().lower()
    return eng in {"paddle", "paddleocr", "ppstructure"}


def extract_table_hints_from_image(
    image: Image.Image,
    *,
    page_number: int,
    source_document: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Best-effort table region hints from PP-Structure / PaddleOCR.

    Returns None when disabled, unavailable, or empty — so the existing
    structured_table / chunker pipeline remains the source of truth.
    """
    if not paddle_table_assist_enabled():
        return None
    try:
        from app.document_processing.ocr.paddle_ocr import paddle_available

        if not paddle_available():
            return None
    except Exception:  # noqa: BLE001
        return None

    # Prefer PPStructure when installed; otherwise skip (do not invent tables).
    try:
        from paddleocr import PPStructure  # type: ignore
    except Exception:  # noqa: BLE001
        logger.info("PPStructure not available; keeping existing table extractor")
        return None

    try:
        import numpy as np

        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        elif image.mode == "L":
            image = image.convert("RGB")
        engine = PPStructure(show_log=False, use_gpu=False)
        result = engine(np.array(image))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Paddle table assist failed on page %s: %s", page_number, exc)
        return None

    if not result:
        return None

    tables: list[dict[str, Any]] = []
    for block in result:
        if not isinstance(block, dict):
            continue
        btype = (block.get("type") or "").lower()
        if btype != "table":
            continue
        entry: dict[str, Any] = {
            "page": page_number,
            "type": "table",
        }
        if source_document:
            entry["source_document"] = source_document
        if block.get("bbox") is not None:
            entry["bbox"] = block.get("bbox")
        if block.get("res") is not None:
            entry["res"] = block.get("res")
        conf = block.get("confidence") or block.get("score")
        if conf is not None:
            try:
                entry["confidence"] = float(conf)
            except (TypeError, ValueError):
                pass
        tables.append(entry)

    if not tables:
        return None
    return {
        "engine": "paddle_ppstructure",
        "page": page_number,
        "tables": tables,
        "note": "Assistive only — existing structured_table remains primary",
    }
