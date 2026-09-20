"""Excel workbook preprocessing with pandas / openpyxl."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.document_processing.types import ExtractedPage, ProcessingResult
from app.models import SourceType


def _dataframe_to_text(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty sheet)"
    # Preserve tabular layout for Phase 3 consumption
    return df.fillna("").to_csv(index=False, sep="|")


def _dataframe_meta(df: pd.DataFrame) -> dict[str, Any]:
    records = df.fillna("").astype(str).to_dict(orient="records")
    return {
        "columns": [str(c) for c in df.columns.tolist()],
        "row_count": int(len(df)),
        "rows": records[:500],  # cap stored rows for huge sheets
    }


def process_excel(path: Path) -> ProcessingResult:
    suffix = path.suffix.lower()
    engine = "openpyxl" if suffix == ".xlsx" else None
    try:
        if suffix == ".xls":
            # xlrd for legacy .xls; fall back to openpyxl errors with clear message
            try:
                book = pd.read_excel(path, sheet_name=None, dtype=str, engine="xlrd")
            except ImportError as exc:
                raise RuntimeError(
                    "Legacy .xls support requires the 'xlrd' package. Prefer .xlsx uploads."
                ) from exc
        else:
            book = pd.read_excel(path, sheet_name=None, dtype=str, engine=engine)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to read Excel workbook: {exc}") from exc

    if not book:
        raise RuntimeError("Excel workbook contains no sheets.")

    pages: list[ExtractedPage] = []
    for index, (sheet_name, df) in enumerate(book.items(), start=1):
        text = _dataframe_to_text(df)
        pages.append(
            ExtractedPage(
                page_number=index,
                text=text,
                source_type=SourceType.EXCEL_SHEET.value,
                sheet_name=str(sheet_name),
                source_location=f"sheet:{sheet_name}",
                content_meta=_dataframe_meta(df),
            )
        )

    return ProcessingResult(
        pages=pages,
        is_scanned=False,
        ocr_used=False,
        file_type="excel",
        page_count=len(pages),
        meta={"sheet_names": [p.sheet_name for p in pages]},
        stage="completed",
    )
