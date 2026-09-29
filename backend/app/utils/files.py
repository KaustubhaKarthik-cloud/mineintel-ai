"""File validation and path helpers for document ingestion."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.config import get_settings

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".png", ".jpg", ".jpeg"}

MIME_BY_EXT = {
    ".pdf": {"application/pdf", "application/x-pdf"},
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/octet-stream",
    },
    ".xls": {
        "application/vnd.ms-excel",
        "application/octet-stream",
    },
    ".png": {"image/png", "application/octet-stream"},
    ".jpg": {"image/jpeg", "application/octet-stream"},
    ".jpeg": {"image/jpeg", "application/octet-stream"},
}

MAGIC_CHECKS = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".xlsx": [b"PK"],  # zip container
    ".xls": [b"\xd0\xcf\x11\xe0"],  # OLE compound
}


class FileValidationError(ValueError):
    """Raised when an upload fails validation (safe for API clients)."""


def project_root() -> Path:
    # backend/app/utils/files.py → parents[3] = mineintel-ai/
    return Path(__file__).resolve().parents[3]


def documents_root() -> Path:
    settings = get_settings()
    raw = Path(settings.documents_dir)
    root = raw if raw.is_absolute() else (project_root() / raw).resolve()
    (root / "original").mkdir(parents=True, exist_ok=True)
    (root / "processed").mkdir(parents=True, exist_ok=True)
    return root


def sanitize_filename(filename: str) -> str:
    """Strip path components and unsafe characters."""
    name = Path(filename.replace("\\", "/")).name
    name = name.strip().replace("\x00", "")
    if not name or name in {".", ".."}:
        name = "upload.bin"
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("._")
    if not name:
        name = "upload.bin"
    # Cap length while preserving extension
    stem = Path(name).stem[:180]
    suffix = Path(name).suffix[:20]
    return f"{stem}{suffix}"


def detect_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_extension(filename: str) -> str:
    ext = detect_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise FileValidationError(f"Unsupported file type '{ext or '(none)'}'. Allowed: {allowed}")
    return ext


def validate_file_size(size: int) -> None:
    settings = get_settings()
    max_bytes = settings.upload_max_size_mb * 1024 * 1024
    if size <= 0:
        raise FileValidationError("Uploaded file is empty.")
    if size > max_bytes:
        raise FileValidationError(
            f"File exceeds maximum size of {settings.upload_max_size_mb} MB."
        )


def validate_magic_bytes(data: bytes, ext: str) -> None:
    expected = MAGIC_CHECKS.get(ext)
    if not expected:
        return
    if not any(data.startswith(sig) for sig in expected):
        raise FileValidationError(
            f"File content does not match declared type '{ext}'. Upload rejected."
        )


def validate_mime(ext: str, mime_type: Optional[str]) -> str:
    allowed = MIME_BY_EXT.get(ext, set())
    if mime_type and mime_type not in allowed and mime_type != "application/octet-stream":
        # Soft check: some browsers send odd MIME; extension+magic is primary
        if not any(mime_type.startswith(a.split("/")[0]) for a in allowed):
            # Still allow if magic passed — return normalized mime
            pass
    return mime_type or next(iter(allowed), "application/octet-stream")


def build_storage_name(original_filename: str, document_id: str) -> str:
    safe = sanitize_filename(original_filename)
    return f"{document_id}_{safe}"


def new_document_id() -> str:
    return str(uuid4())


def classify_file_kind(ext: str) -> str:
    if ext == ".pdf":
        return "pdf"
    if ext in {".xlsx", ".xls"}:
        return "excel"
    if ext in {".png", ".jpg", ".jpeg"}:
        return "image"
    return "unknown"
