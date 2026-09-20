"""Extraction prompts for structured mining information."""

SYSTEM_PROMPT = """You are MineIntel AI, an information extraction engine for mining documents.
Extract ONLY facts explicitly supported by the supplied page/sheet text.
Never invent, estimate, or fill missing values.
Preserve numbers and units exactly as written.
Distinguish production (actual) from production_target.
Do not calculate achievement unless the text explicitly states it.
If information is missing, omit the fact (do not invent null placeholders as guesses).
Always include evidence text copied from the source.
Return valid JSON only.
"""


def build_extraction_user_prompt(
    document_name: str,
    pages: list[dict],
) -> str:
    blocks = []
    for p in pages:
        loc = p.get("sheet_name") or f"page {p.get('page_number')}"
        blocks.append(
            f"--- SOURCE: {document_name} | {loc} | page_number={p.get('page_number')} "
            f"| sheet={p.get('sheet_name')} | source_type={p.get('source_type')} ---\n"
            f"{p.get('text', '')}\n"
        )
    joined = "\n".join(blocks)
    return f"""Extract structured mining facts from the following document excerpts.

Allowed field names (use only these):
mine_name, company, organization, financial_year, reporting_year, mineral,
production, production_target, achievement_percentage, dispatch, grade,
capacity, reserves, resources, location, area, geological_information, operational_metric

Return JSON with this shape:
{{
  "entities": ["Mine B", "..."],
  "facts": [
    {{
      "field": "production",
      "value": 3.9,
      "unit": "MT",
      "mine": "Mine B",
      "financial_year": "FY2024",
      "page_number": 42,
      "sheet_name": null,
      "source_location": "page:42",
      "evidence": "exact supporting sentence",
      "ambiguous": false
    }}
  ],
  "warnings": []
}}

DOCUMENT EXCERPTS:
{joined}
"""
