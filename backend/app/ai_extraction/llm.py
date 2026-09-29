"""LLM provider abstraction for Phase 3 extraction."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.ai_extraction.prompts import SYSTEM_PROMPT, build_extraction_user_prompt
from app.ai_extraction.schemas import LLMExtractionResponse, LLMFactDraft
from app.config import get_settings


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def extract_structured_information(
        self,
        document_name: str,
        pages: list[dict[str, Any]],
    ) -> LLMExtractionResponse:
        raise NotImplementedError


def _parse_json_response(raw: str) -> LLMExtractionResponse:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # try to find first JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise LLMError("LLM returned invalid JSON.") from exc
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc2:
            raise LLMError("LLM returned invalid JSON.") from exc2
    try:
        return LLMExtractionResponse.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise LLMError("LLM JSON did not match the expected schema.") from exc


class MockLLMProvider(LLMProvider):
    """Heuristic extractor for offline / tests — never fabricates beyond regex matches."""

    name = "mock"

    def extract_structured_information(
        self,
        document_name: str,
        pages: list[dict[str, Any]],
    ) -> LLMExtractionResponse:
        facts: list[LLMFactDraft] = []
        entities: set[str] = set()
        warnings: list[str] = []

        for page in pages:
            text = page.get("text") or ""
            page_number = page.get("page_number")
            sheet_name = page.get("sheet_name")
            source_location = page.get("source_location")
            is_ocr = bool(page.get("is_ocr"))

            # Mine B produced 3.9 MT during FY2024 against a target of 5.0 MT
            prod = re.search(
                r"(?P<mine>[\w\s\-/]+?)\s+produced\s+(?P<val>\d+(?:\.\d+)?)\s*"
                r"(?P<unit>MT|Mt|mt|tonnes|tons|kt)\b"
                r"(?:[^\n.]{0,80}?during\s+(?P<fy>FY\s?\d{4}|\d{4}-\d{2}|\d{4}/\d{2}))?",
                text,
                re.IGNORECASE,
            )
            if prod:
                mine = prod.group("mine").strip()
                entities.add(mine)
                fy = (prod.group("fy") or "").replace(" ", "") or None
                evidence = prod.group(0).strip()
                facts.append(
                    LLMFactDraft(
                        field="production",
                        value=float(prod.group("val")),
                        unit=prod.group("unit"),
                        mine=mine,
                        financial_year=fy,
                        page_number=page_number,
                        sheet_name=sheet_name,
                        source_location=source_location,
                        evidence=evidence,
                        ambiguous=is_ocr,
                    )
                )

            target = re.search(
                r"(?:against\s+a\s+)?target\s+of\s+(?P<val>\d+(?:\.\d+)?)\s*"
                r"(?P<unit>MT|Mt|mt|tonnes|tons|kt)\b",
                text,
                re.IGNORECASE,
            )
            if target:
                mine = None
                if prod:
                    mine = prod.group("mine").strip()
                facts.append(
                    LLMFactDraft(
                        field="production_target",
                        value=float(target.group("val")),
                        unit=target.group("unit"),
                        mine=mine,
                        financial_year=(prod.group("fy").replace(" ", "") if prod and prod.group("fy") else None),
                        page_number=page_number,
                        sheet_name=sheet_name,
                        source_location=source_location,
                        evidence=target.group(0).strip(),
                        ambiguous=is_ocr,
                    )
                )

            ach = re.search(
                r"(?:achievement|achieved)\s*(?:of|=|:)?\s*(?P<val>\d+(?:\.\d+)?)\s*%",
                text,
                re.IGNORECASE,
            )
            if ach:
                facts.append(
                    LLMFactDraft(
                        field="achievement_percentage",
                        value=float(ach.group("val")),
                        unit="%",
                        mine=prod.group("mine").strip() if prod else None,
                        financial_year=(prod.group("fy").replace(" ", "") if prod and prod.group("fy") else None),
                        page_number=page_number,
                        sheet_name=sheet_name,
                        source_location=source_location,
                        evidence=ach.group(0).strip(),
                        ambiguous=is_ocr,
                    )
                )

            # OCR-like noisy production: Pr0ducti0n: 3.9 M?
            noisy = re.search(
                r"Pr[o0]ducti[o0]n\s*[:=]\s*(?P<val>\d+(?:\.\d+)?)\s*M\??",
                text,
                re.IGNORECASE,
            )
            if noisy and not prod:
                facts.append(
                    LLMFactDraft(
                        field="production",
                        value=float(noisy.group("val")),
                        unit="MT",
                        mine=None,
                        page_number=page_number,
                        sheet_name=sheet_name,
                        source_location=source_location,
                        evidence=noisy.group(0).strip(),
                        ambiguous=True,
                    )
                )
                warnings.append("OCR-like production string detected; review recommended.")

            # Excel pipe tables: Mine B|3.9|5.0
            if "|" in text and ("Mine" in text or "Production" in text):
                for line in text.splitlines():
                    parts = [c.strip() for c in line.split("|")]
                    if len(parts) >= 3 and re.match(r"Mine\s+\w+", parts[0], re.I):
                        if re.match(r"^\d+(\.\d+)?$", parts[1] or ""):
                            entities.add(parts[0])
                            facts.append(
                                LLMFactDraft(
                                    field="production",
                                    value=float(parts[1]),
                                    unit="MT",
                                    mine=parts[0],
                                    page_number=page_number,
                                    sheet_name=sheet_name,
                                    source_location=source_location or f"sheet:{sheet_name}",
                                    evidence=line.strip(),
                                    ambiguous=False,
                                )
                            )
                        if len(parts) >= 3 and re.match(r"^\d+(\.\d+)?$", parts[2] or ""):
                            facts.append(
                                LLMFactDraft(
                                    field="production_target",
                                    value=float(parts[2]),
                                    unit="MT",
                                    mine=parts[0],
                                    page_number=page_number,
                                    sheet_name=sheet_name,
                                    source_location=source_location or f"sheet:{sheet_name}",
                                    evidence=line.strip(),
                                    ambiguous=False,
                                )
                            )

            grade = re.search(
                r"(?:grade|ore grade)\s*(?:of|=|:)?\s*(?P<val>\d+(?:\.\d+)?)\s*%",
                text,
                re.IGNORECASE,
            )
            if grade:
                facts.append(
                    LLMFactDraft(
                        field="grade",
                        value=float(grade.group("val")),
                        unit="%",
                        page_number=page_number,
                        sheet_name=sheet_name,
                        source_location=source_location,
                        evidence=grade.group(0).strip(),
                        ambiguous=is_ocr,
                    )
                )

            reserves = re.search(
                r"reserves?\s*(?:of|=|:)?\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>MT|Mt|mt|tonnes)",
                text,
                re.IGNORECASE,
            )
            if reserves:
                facts.append(
                    LLMFactDraft(
                        field="reserves",
                        value=float(reserves.group("val")),
                        unit=reserves.group("unit"),
                        page_number=page_number,
                        sheet_name=sheet_name,
                        source_location=source_location,
                        evidence=reserves.group(0).strip(),
                        ambiguous=is_ocr,
                    )
                )

        return LLMExtractionResponse(
            entities=sorted(entities),
            facts=facts,
            warnings=warnings,
        )


class OpenAILLMProvider(LLMProvider):
    name = "openai"

    def extract_structured_information(
        self,
        document_name: str,
        pages: list[dict[str, Any]],
    ) -> LLMExtractionResponse:
        settings = get_settings()
        if not settings.llm_api_key:
            raise LLMError("LLM API key is not configured.")

        payload = {
            "model": settings.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_extraction_user_prompt(document_name, pages),
                },
            ],
        }
        url = settings.llm_api_base.rstrip("/") + "/chat/completions"
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
        except httpx.TimeoutException as exc:
            raise LLMError("LLM request timed out.") from exc
        except httpx.HTTPError as exc:
            raise LLMError("LLM provider request failed.") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected LLM provider response.") from exc

        return _parse_json_response(content)


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    provider = (settings.llm_provider or "mock").lower().strip()
    if provider in {"openai", "compatible"} and settings.llm_api_key:
        return OpenAILLMProvider()
    return MockLLMProvider()
