"""Phase 3 AI extraction — Pydantic schemas for LLM I/O."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class LLMFactDraft(BaseModel):
    field: str
    value: Optional[str | float | int] = None
    unit: Optional[str] = None
    mine: Optional[str] = None
    entity: Optional[str] = None
    financial_year: Optional[str] = None
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    source_location: Optional[str] = None
    evidence: Optional[str] = None
    ambiguous: bool = False


class LLMExtractionResponse(BaseModel):
    entities: list[str] = Field(default_factory=list)
    facts: list[LLMFactDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PageBatch(BaseModel):
    page_id: str
    page_number: int
    source_type: str
    sheet_name: Optional[str] = None
    source_location: Optional[str] = None
    text: str
    is_ocr: bool = False


ALLOWED_FIELDS = {
    "mine_name",
    "company",
    "organization",
    "financial_year",
    "reporting_year",
    "mineral",
    "production",
    "production_target",
    "achievement_percentage",
    "dispatch",
    "grade",
    "capacity",
    "reserves",
    "resources",
    "location",
    "area",
    "geological_information",
    "operational_metric",
}

ALLOWED_UNITS = {
    "MT",
    "Mt",
    "mt",
    "tonnes",
    "tons",
    "kt",
    "kg",
    "%",
    "pct",
    "ha",
    "hectares",
    "sq km",
    "km2",
    "m",
    "million tonnes",
    "Mm3",
    "m3",
}
