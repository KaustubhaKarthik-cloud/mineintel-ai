"""OCR helpers for numeric table refinement (digit-confusion correction)."""

from __future__ import annotations

import re

# Common single-glyph OCR confusions for printed digits
_DIGIT_CONFUSIONS = {
    "0": set("8OQD"),
    "1": set("7lI|"),
    "2": set("Z"),
    "3": set("58B"),
    "4": set("A"),
    "5": set("36S"),
    "6": set("8G"),
    "7": set("1"),
    "8": set("0B3"),
    "9": set("gq"),
}


def digits_confusable(a: str, b: str) -> bool:
    """True when a and b differ by a single OCR digit/glyph confusion."""
    if a == b:
        return True
    if len(a) != len(b):
        return False
    diffs = 0
    for ca, cb in zip(a, b):
        if ca == cb:
            continue
        if ca == "." or cb == ".":
            return False
        conf_a = _DIGIT_CONFUSIONS.get(ca, set())
        conf_b = _DIGIT_CONFUSIONS.get(cb, set())
        if cb in conf_a or ca in conf_b or cb.upper() in conf_a or ca.upper() in conf_b:
            diffs += 1
            if diffs > 1:
                return False
            continue
        return False
    return diffs == 1


def looks_like_numeric_table(text: str) -> bool:
    if not text:
        return False
    decimals = re.findall(r"(?<!\()\b\d+\.\d{2}\b", text)
    if len(decimals) < 6:
        return False
    lower = text.lower()
    return any(k in lower for k in ("actual", "target", "production", "overburden", "lignite"))


def merge_ocr_decimals(base_text: str, detail_text: str) -> str:
    """Prefer detail-OCR decimals when they are digit-confusable variants of base tokens.

    Only replaces a value when the same left/right numeric neighbors appear in the
    detail pass (local consensus). That corrects single-digit OCR confusions
    without swapping unrelated table cells.
    """
    if not base_text or not detail_text:
        return base_text

    num_re = re.compile(r"(?<!\()\b\d+\.\d{2}\b")
    base_vals = [m.group(0) for m in num_re.finditer(base_text)]
    detail_vals = [m.group(0) for m in num_re.finditer(detail_text)]
    if len(base_vals) < 3 or len(detail_vals) < 3:
        return base_text

    replacements: dict[str, str] = {}
    for i in range(len(base_vals)):
        b = base_vals[i]
        left = base_vals[i - 1] if i > 0 else None
        right = base_vals[i + 1] if i + 1 < len(base_vals) else None
        for j, d in enumerate(detail_vals):
            if d == b or not digits_confusable(b, d):
                continue
            d_left = detail_vals[j - 1] if j > 0 else None
            d_right = detail_vals[j + 1] if j + 1 < len(detail_vals) else None
            left_ok = left is not None and d_left == left
            right_ok = right is not None and d_right == right
            if left is not None and right is not None:
                if left_ok and right_ok:
                    replacements[b] = d
                    break
            elif left_ok or right_ok:
                replacements[b] = d
                break

    if not replacements:
        return base_text

    def _replace(match: re.Match[str]) -> str:
        tok = match.group(0)
        return replacements.get(tok, tok)

    return num_re.sub(_replace, base_text)
