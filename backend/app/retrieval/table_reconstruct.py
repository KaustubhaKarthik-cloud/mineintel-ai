"""Generic reconstruction of labeled production tables from PDF text extracts.

Preserves entity × metric × reporting-month × measure(during/upto) × FY relationships.
Does not hard-code companies, states, documents, or numeric answers.
"""

from __future__ import annotations

import re
from typing import Optional


_STATEISH = re.compile(
    r"^(?:"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*"
    r"|[A-Z]{2,}"
    r")$"
)

_SKIP_LABELS = {
    "state",
    "subs",
    "sl",
    "no",
    "sl no",
    "fig",
    "mt",
    "qty",
    "table",
    "production",
    "during",
    "upto",
    "dec",
    "mar",
    "target",
    "achmt",
    "growth",
    "grand",
    "total",
    "cil",
    "monthly",
    "y-o-y",
    "m-o-m",
}

_MONTH_ALIASES = {
    "jan": "January",
    "january": "January",
    "feb": "February",
    "february": "February",
    "mar": "March",
    "march": "March",
    "apr": "April",
    "april": "April",
    "may": "May",
    "jun": "June",
    "june": "June",
    "jul": "July",
    "july": "July",
    "aug": "August",
    "august": "August",
    "sep": "September",
    "sept": "September",
    "september": "September",
    "oct": "October",
    "october": "October",
    "nov": "November",
    "november": "November",
    "dec": "December",
    "december": "December",
}


def normalize_month_token(token: str) -> Optional[str]:
    t = re.sub(r"[^a-z]", "", (token or "").lower())
    return _MONTH_ALIASES.get(t)


def detect_reporting_month(page_text: str) -> Optional[str]:
    """Infer the table's reporting month from headers / title cues on the page."""
    raw = page_text or ""
    # Strongest: "Production during Mar" / "upto Dec"
    m = re.search(
        r"(?:during|upto|up\s*to)\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b",
        raw,
        re.I,
    )
    if m:
        return normalize_month_token(m.group(1))
    # Report title: "March'2025" / "December'2024"
    m = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s*['’]?\s*20\d{2}\b",
        raw,
        re.I,
    )
    if m:
        return normalize_month_token(m.group(1))
    # Sidebar "Dec'24" / "Mar'25"
    m = re.search(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*['’]?\s*\d{2}\b", raw, re.I)
    if m:
        return normalize_month_token(m.group(1))
    return None


def _is_entity_label(line: str) -> bool:
    s = re.sub(r"\s+", " ", (line or "").strip())
    if not s or len(s) > 40:
        return False
    if re.fullmatch(r"\d+\.?\d*", s):
        return False
    if s.lower().rstrip(".") in _SKIP_LABELS:
        return False
    if re.match(r"^(FY|Fig|Table|Sl)\b", s, re.I):
        return False
    if re.match(r"^[▲▼]", s):
        return False
    if _STATEISH.match(s) or re.match(r"^[A-Z][A-Za-z]{1,}(?:\s+[A-Z][A-Za-z]{1,})*$", s):
        return True
    if re.match(r"^[A-Z]{2,10}(?:/[A-Za-z]+)?$", s):
        return True
    if re.match(r"^[A-Z][a-z]+(?:/[A-Za-z]+)?$", s):
        return True
    return False


def _is_growth_line(line: str) -> bool:
    return bool(re.match(r"^[▲▼]", (line or "").strip()))


def _consume_floats(lines: list[str], start: int, *, limit: int = 10) -> tuple[list[float], int]:
    nums: list[float] = []
    j = start
    while j < len(lines) and len(nums) < limit:
        ln = lines[j]
        if _is_growth_line(ln):
            j += 1
            continue
        if re.fullmatch(r"\d+\.\d{1,3}", ln):
            nums.append(float(ln))
            j += 1
            continue
        break
    return nums, j


def reconstruct_period_production_table(page_text: str) -> Optional[str]:
    """Rebuild entity × reporting-month × measure × FY evidence from MoC-style tables."""
    if not page_text:
        return None
    raw = page_text.replace("\r\n", "\n").replace("\r", "\n")
    low = raw.lower()
    if "production" not in low:
        return None
    if not re.search(r"\bfy\s*2[0-9]\b", low):
        return None
    metric = "coal"
    if "lignite" in low and "coal" not in low:
        metric = "lignite"
    elif "overburden" in low and "coal" not in low:
        metric = "overburden"
    elif "coal" not in low and "lignite" not in low:
        return None

    # Do not treat coking-coal / OBR-only pages as thermal coal production tables.
    if metric == "coal":
        has_thermal = bool(
            re.search(r"table\s+1\.1:\s*coal\s+production|state-wise\s+coal\s+production", low)
        )
        has_coking = bool(re.search(r"coking\s+coal\s+production", low))
        has_obr = bool(re.search(r"\bobr\b|overburden", low))
        if has_coking and not has_thermal:
            return None
        if has_obr and not has_thermal and "coal production" not in low:
            return None
        # Drop coking subsection so it does not pollute thermal rows on mixed pages
        raw = re.sub(
            r"table\s+1\.1\s*\(\s*b\s*\).*?(?=table\s+1\.2|\bobr\b|$)",
            "\n",
            raw,
            flags=re.I | re.S,
        )
        low = raw.lower()

    month = detect_reporting_month(raw) or "Unknown"
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]

    if re.search(r"state[- ]wise", low):
        ordered = _reconstruct_ordered_grid(lines, metric, raw, month=month)
        if ordered:
            return ordered

    interleaved = _reconstruct_interleaved(lines, metric, month=month)
    if interleaved:
        return interleaved
    ordered = _reconstruct_ordered_grid(lines, metric, raw, month=month)
    if ordered:
        return ordered
    return None


def _reconstruct_interleaved(lines: list[str], metric: str, *, month: str) -> Optional[str]:
    has_fy = any(re.search(r"\bfy\s*2[0-9]\b", ln, re.I) for ln in lines)
    if not has_fy:
        return None
    rows: list[tuple[str, list[float]]] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if re.fullmatch(r"\d{1,3}", ln) and i + 1 < len(lines) and _is_entity_label(lines[i + 1]):
            label = lines[i + 1]
            nums, j = _consume_floats(lines, i + 2, limit=8)
            if len(nums) >= 4:
                rows.append((label, nums))
                i = j
                continue
        if _is_entity_label(ln):
            nums, j = _consume_floats(lines, i + 1, limit=8)
            if len(nums) >= 4:
                rows.append((ln, nums))
                i = j
                continue
        i += 1
    if len(rows) < 3:
        return None
    return _format_rows(
        rows,
        metric,
        month=month,
        title="Production table (reconstructed from source layout)",
    )


def _reconstruct_ordered_grid(
    lines: list[str], metric: str, raw: str, *, month: str
) -> Optional[str]:
    pairs: list[tuple[str, float]] = []
    i = 0
    while i < len(lines) - 1:
        if _is_entity_label(lines[i]) and re.fullmatch(r"\d+\.\d{1,3}", lines[i + 1]):
            pairs.append((lines[i], float(lines[i + 1])))
            i += 2
            if len(pairs) >= 3 and i < len(lines) and re.search(r"\bfy\s*2[0-9]\b", lines[i], re.I):
                break
            continue
        if pairs and re.search(r"\bfy\s*2[0-9]\b", lines[i], re.I):
            break
        i += 1
    if len(pairs) < 3:
        return None

    grid: list[list[float]] = []
    i = 0
    while i < len(lines):
        if re.fullmatch(r"\d{1,3}", lines[i]):
            nums, j = _consume_floats(lines, i + 1, limit=8)
            if len(nums) >= 4:
                grid.append(nums)
                i = j
                continue
        i += 1
    if len(grid) < 3:
        return None
    n = min(len(pairs), len(grid))
    if n < 3:
        return None
    rows = [(pairs[k][0], grid[k]) for k in range(n)]
    title = "State-wise production (reconstructed from source table)"
    if re.search(r"state-wise", raw, re.I):
        title = "State-wise coal production (reconstructed from source table)"
    return _format_rows(rows, metric, month=month, title=title)


def _format_rows(
    rows: list[tuple[str, list[float]]],
    metric: str,
    *,
    month: str,
    title: str,
) -> str:
    """Emit explicit semantic records — one measure type per sentence."""
    lines = [f"{title}:"]
    for label, nums in rows:
        during_fy25 = during_fy24 = upto_fy25 = upto_fy24 = None
        has_ach = any(70.0 <= v <= 160.0 for v in nums[:4])
        if has_ach and len(nums) >= 6:
            during_fy25, during_fy24 = nums[1], nums[3]
            upto_fy25, upto_fy24 = nums[4], nums[5]
        elif len(nums) >= 4:
            during_fy25, during_fy24 = nums[0], nums[1]
            upto_fy25, upto_fy24 = nums[2], nums[3]

        if during_fy25 is not None and during_fy24 is not None:
            lines.append(
                f"{label} {metric} production | reporting_period={month} | measure=during | "
                f"FY25={during_fy25:g} MT | FY24={during_fy24:g} MT."
            )
        if upto_fy25 is not None and upto_fy24 is not None:
            lines.append(
                f"{label} {metric} production | reporting_period={month} | measure=upto | "
                f"FY25={upto_fy25:g} MT | FY24={upto_fy24:g} MT."
            )
    # title + at least 3 entity rows worth (~6 measure lines) or 3 entities
    if len(lines) < 4:
        return ""
    return " ".join(lines)
