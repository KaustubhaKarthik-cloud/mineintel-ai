"""PaddleOCR integration for MineIntel (optional primary OCR engine).

Kept separate from Tesseract (`ocr_processor.py`) so the SIH pipeline can
fall back without removing existing OCR. Requires paddlepaddle + paddleocr
in the venv; if missing, `paddle_available()` is False and callers fall back.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

from PIL import Image

from app.config import get_settings
from app.document_processing.ocr_processor import OCRResult

logger = logging.getLogger(__name__)


class PaddleOCRUnavailableError(RuntimeError):
    """PaddleOCR package or model init failed."""


@dataclass
class PaddleLine:
    """One OCR line/region as returned by Paddle (no invented fields)."""

    text: str
    confidence: Optional[float] = None
    bbox: Optional[list[list[float]]] = None  # [[x,y], ...] when provided


@dataclass
class PaddlePageResult:
    page: int
    text: str
    confidence: Optional[float] = None
    lines: list[PaddleLine] = field(default_factory=list)
    engine: str = "paddle"


def paddle_available() -> bool:
    try:
        import paddle  # noqa: F401
        import paddleocr  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _is_decimal_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+\.\d{2}", token))


@lru_cache(maxsize=1)
def _get_paddle_ocr():
    """Lazy singleton — model download happens once per process."""
    if not paddle_available():
        raise PaddleOCRUnavailableError(
            "paddlepaddle/paddleocr are not installed. "
            "See docs/OCR_PADDLE.md for install commands."
        )
    settings = get_settings()
    lang = (settings.paddle_ocr_lang or "en").strip() or "en"
    # Skip slow host connectivity probe on every process start
    import os

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:  # noqa: BLE001
        raise PaddleOCRUnavailableError(f"Failed to import PaddleOCR: {exc}") from exc

    # PaddleOCR 2.x / 3.x constructor kwargs differ — try safest first.
    candidates = [
        {"lang": lang},
        {"lang": lang, "use_textline_orientation": True},
        {"lang": lang, "use_angle_cls": True},
        {"lang": lang, "use_angle_cls": True, "show_log": False, "use_gpu": False},
    ]
    last_exc: Exception | None = None
    for kwargs in candidates:
        try:
            return PaddleOCR(**kwargs)
        except (TypeError, ValueError) as exc:
            last_exc = exc
            continue
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    raise PaddleOCRUnavailableError(
        f"Failed to initialize PaddleOCR: {last_exc}"
    ) from last_exc


def _normalize_bbox(raw: Any) -> Optional[list[list[float]]]:
    if raw is None:
        return None
    try:
        pts = []
        for p in raw:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                pts.append([float(p[0]), float(p[1])])
        return pts or None
    except (TypeError, ValueError):
        return None


def _parse_ocr_payload(payload: Any) -> list[PaddleLine]:
    """Normalize PaddleOCR 2.x `ocr()` and 3.x `predict()` outputs into lines."""
    lines: list[PaddleLine] = []
    if payload is None:
        return lines

    # PaddleX OCRResult is dict-like (has .get / .keys) but may not be isinstance(dict)
    if hasattr(payload, "get") and callable(payload.get) and (
        payload.get("rec_texts") is not None or payload.get("texts") is not None
    ):
        texts = payload.get("rec_texts") or payload.get("texts") or []
        scores = payload.get("rec_scores") or payload.get("scores") or []
        polys = (
            payload.get("dt_polys")
            or payload.get("rec_polys")
            or payload.get("boxes")
            or []
        )
        for i, text in enumerate(texts):
            if not text or not str(text).strip():
                continue
            conf = None
            if i < len(scores):
                try:
                    conf = float(scores[i])
                    if 0.0 <= conf <= 1.0:
                        conf = conf * 100.0
                except (TypeError, ValueError):
                    conf = None
            bbox = None
            if i < len(polys):
                try:
                    poly = polys[i]
                    # numpy arrays → list
                    if hasattr(poly, "tolist"):
                        poly = poly.tolist()
                    bbox = _normalize_bbox(poly)
                except Exception:  # noqa: BLE001
                    bbox = None
            lines.append(
                PaddleLine(
                    text=str(text).strip(),
                    confidence=round(conf, 2) if conf is not None else None,
                    bbox=bbox,
                )
            )
        return lines

    # 2.x: result = [ [ [bbox, (text, conf)], ... ] ]  or None page
    if isinstance(payload, list):
        page_items = payload
        # unwrap single-page list-of-lines
        if page_items and isinstance(page_items[0], list) and page_items[0] and isinstance(
            page_items[0][0], (list, tuple)
        ):
            # could be [lines] or [[lines]]
            first = page_items[0]
            if first and isinstance(first[0], (list, tuple)) and len(first[0]) == 2:
                page_items = first
        for item in page_items:
            if not item:
                continue
            # line = [bbox, (text, score)]
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                bbox_raw, info = item[0], item[1]
                text = None
                conf = None
                if isinstance(info, (list, tuple)) and len(info) >= 1:
                    text = str(info[0]) if info[0] is not None else None
                    if len(info) >= 2 and info[1] is not None:
                        try:
                            conf = float(info[1])
                            # paddle often returns 0..1; keep scale consistent with tesseract (0..100)
                            if 0.0 <= conf <= 1.0:
                                conf = conf * 100.0
                        except (TypeError, ValueError):
                            conf = None
                elif isinstance(info, dict):
                    text = info.get("text") or info.get("transcription")
                    conf = info.get("score") or info.get("confidence")
                    if conf is not None:
                        try:
                            conf = float(conf)
                            if 0.0 <= conf <= 1.0:
                                conf = conf * 100.0
                        except (TypeError, ValueError):
                            conf = None
                if text and str(text).strip():
                    lines.append(
                        PaddleLine(
                            text=str(text).strip(),
                            confidence=round(conf, 2) if conf is not None else None,
                            bbox=_normalize_bbox(bbox_raw),
                        )
                    )
            elif isinstance(item, dict) or (hasattr(item, "get") and callable(getattr(item, "get", None))):
                nested = _parse_ocr_payload(item)
                if nested:
                    lines.extend(nested)
                else:
                    text = item.get("text") or item.get("transcription")
                    conf = item.get("score") or item.get("confidence")
                    bbox = item.get("bbox") or item.get("poly") or item.get("points")
                    if conf is not None:
                        try:
                            conf = float(conf)
                            if 0.0 <= conf <= 1.0:
                                conf = conf * 100.0
                        except (TypeError, ValueError):
                            conf = None
                    if text and str(text).strip():
                        lines.append(
                            PaddleLine(
                                text=str(text).strip(),
                                confidence=round(conf, 2) if conf is not None else None,
                                bbox=_normalize_bbox(bbox),
                            )
                        )
        return lines

    # object with attributes
    for attr in ("rec_texts", "texts"):
        if hasattr(payload, attr):
            return _parse_ocr_payload(
                {
                    "rec_texts": getattr(payload, "rec_texts", None) or getattr(payload, "texts", None),
                    "rec_scores": getattr(payload, "rec_scores", None) or getattr(payload, "scores", None),
                    "dt_polys": getattr(payload, "dt_polys", None)
                    or getattr(payload, "rec_polys", None)
                    or getattr(payload, "boxes", None),
                }
            )
    return lines


def _run_paddle_on_array(img_array: Any) -> list[PaddleLine]:
    ocr = _get_paddle_ocr()
    # Prefer predict (3.x); fall back to ocr (2.x)
    raw = None
    if hasattr(ocr, "predict"):
        try:
            raw = ocr.predict(img_array)
        except Exception:  # noqa: BLE001
            raw = None
    if raw is None and hasattr(ocr, "ocr"):
        try:
            # cls=True for angle classification when supported
            try:
                raw = ocr.ocr(img_array, cls=True)
            except TypeError:
                raw = ocr.ocr(img_array)
        except Exception as exc:  # noqa: BLE001
            raise PaddleOCRUnavailableError(f"PaddleOCR inference failed: {exc}") from exc

    if raw is None:
        return []

    # 3.x: list[OCRResult] (dict-like)
    if isinstance(raw, list) and raw:
        first = raw[0]
        if hasattr(first, "get") and callable(first.get) and (
            first.get("rec_texts") is not None or first.get("texts") is not None
        ):
            # merge all pages/chunks
            out: list[PaddleLine] = []
            for page in raw:
                out.extend(_parse_ocr_payload(page))
            return out
        # 2.x style list-of-lines
        if isinstance(first, list) and first and isinstance(first[0], (list, tuple)) and len(first[0]) == 2:
            return _parse_ocr_payload(first)
        return _parse_ocr_payload(raw)

    return _parse_ocr_payload(raw)


def ocr_pil_image_paddle(
    image: Image.Image,
    *,
    page_number: int = 1,
) -> PaddlePageResult:
    """Run PaddleOCR on a PIL image; return text + optional boxes/confidence."""
    import numpy as np

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")

    arr = np.array(image)
    lines = _run_paddle_on_array(arr)
    texts = [ln.text for ln in lines if ln.text]
    confs = [ln.confidence for ln in lines if ln.confidence is not None]
    mean = round(sum(confs) / len(confs), 2) if confs else None
    return PaddlePageResult(
        page=page_number,
        text="\n".join(texts).strip(),
        confidence=mean,
        lines=lines,
        engine="paddle",
    )


def paddle_to_ocr_result(page: PaddlePageResult) -> OCRResult:
    """Adapt Paddle output to the shared OCRResult used by the evidence pipeline."""
    low_words: list[str] = []
    low_decimals: list[str] = []
    boxes: list[dict[str, Any]] = []
    for ln in page.lines:
        entry: dict[str, Any] = {"text": ln.text}
        if ln.confidence is not None:
            entry["confidence"] = ln.confidence
        if ln.bbox is not None:
            entry["bbox"] = ln.bbox
        boxes.append(entry)
        if ln.confidence is not None and ln.confidence < 70:
            low_words.append(ln.text)
            for tok in ln.text.split():
                if _is_decimal_token(tok):
                    low_decimals.append(tok)

    return OCRResult(
        text=page.text,
        mean_confidence=page.confidence,
        word_count=len(page.lines),
        low_confidence_words=low_words[:40],
        low_confidence_decimals=list(dict.fromkeys(low_decimals))[:20],
        boxes=boxes,
        engine="paddle",
        page=page.page,
    )


def ocr_pil_image_detailed_paddle(
    image: Image.Image,
    *,
    page_number: int = 1,
) -> OCRResult:
    return paddle_to_ocr_result(ocr_pil_image_paddle(image, page_number=page_number))


def page_result_dict(page: PaddlePageResult) -> dict[str, Any]:
    """SIH traceability shape: page / text / confidence / bbox (only if present)."""
    out: dict[str, Any] = {
        "page": page.page,
        "text": page.text,
        "engine": page.engine,
    }
    if page.confidence is not None:
        out["confidence"] = page.confidence
    bboxes = [ln.bbox for ln in page.lines if ln.bbox is not None]
    if bboxes:
        out["bbox"] = bboxes
    return out
