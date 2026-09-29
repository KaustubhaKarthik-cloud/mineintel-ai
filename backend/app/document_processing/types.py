"""Shared types for document processors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    source_type: str
    sheet_name: Optional[str] = None
    source_location: Optional[str] = None
    content_meta: Optional[dict[str, Any]] = None


@dataclass
class ProcessingResult:
    pages: list[ExtractedPage] = field(default_factory=list)
    is_scanned: bool = False
    ocr_used: bool = False
    file_type: str = ""
    page_count: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    stage: str = "completed"
