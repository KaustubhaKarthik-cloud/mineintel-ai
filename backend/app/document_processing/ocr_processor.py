"""Tesseract OCR helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

from app.config import get_settings

_DEFAULT_WINDOWS_PATHS = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]


class OCRUnavailableError(RuntimeError):
    """Tesseract binary or pytesseract is not available."""


@dataclass
class OCRResult:
    text: str
    mean_confidence: Optional[float] = None
    word_count: int = 0
    low_confidence_words: list[str] = field(default_factory=list)
    low_confidence_decimals: list[str] = field(default_factory=list)
    # Optional provenance for SIH evidence (Paddle fills boxes; Tesseract leaves empty)
    boxes: list = field(default_factory=list)
    engine: str = "tesseract"
    page: Optional[int] = None


def _resolve_tesseract_cmd() -> Optional[str]:
    settings = get_settings()
    if settings.tesseract_cmd:
        return settings.tesseract_cmd
    for candidate in _DEFAULT_WINDOWS_PATHS:
        if candidate.is_file():
            return str(candidate)
    return None


def _configure_tesseract() -> None:
    import pytesseract

    cmd = _resolve_tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd


def ocr_available() -> bool:
    try:
        import pytesseract

        _configure_tesseract()
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


def _is_decimal_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+\.\d{2}", token))


def ocr_pil_image(image: Image.Image, lang: Optional[str] = None) -> str:
    return ocr_pil_image_detailed(image, lang=lang).text


def ocr_pil_image_detailed(image: Image.Image, lang: Optional[str] = None) -> OCRResult:
    """OCR with per-word confidence when Tesseract provides it."""
    try:
        import pytesseract
    except ImportError as exc:
        raise OCRUnavailableError("pytesseract is not installed.") from exc

    _configure_tesseract()
    settings = get_settings()
    language = lang or settings.ocr_language
    try:
        text = (pytesseract.image_to_string(image, lang=language) or "").strip()
        data = pytesseract.image_to_data(
            image, lang=language, output_type=pytesseract.Output.DICT
        )
    except Exception as exc:  # noqa: BLE001
        raise OCRUnavailableError(
            "OCR failed. Ensure Tesseract is installed and TESSERACT_CMD is set if needed."
        ) from exc

    confs: list[float] = []
    low_words: list[str] = []
    low_decimals: list[str] = []
    words = data.get("text") or []
    conf_raw = data.get("conf") or []
    for word, conf in zip(words, conf_raw):
        w = (word or "").strip()
        try:
            c = float(conf)
        except (TypeError, ValueError):
            continue
        if not w or c < 0:
            continue
        confs.append(c)
        if c < 70:
            low_words.append(w)
            if _is_decimal_token(w):
                low_decimals.append(w)

    mean = round(sum(confs) / len(confs), 2) if confs else None
    return OCRResult(
        text=text,
        mean_confidence=mean,
        word_count=len(confs),
        low_confidence_words=low_words[:40],
        low_confidence_decimals=list(dict.fromkeys(low_decimals))[:20],
    )


def ocr_image_bytes(data: bytes, lang: Optional[str] = None) -> str:
    image = Image.open(BytesIO(data))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return ocr_pil_image(image, lang=lang)


def ocr_image_path(path: str, lang: Optional[str] = None) -> str:
    image = Image.open(path)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return ocr_pil_image(image, lang=lang)
