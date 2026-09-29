"""Phase 5 — validation & contradiction detection."""

from app.validation.service import (
    ValidationError,
    confirm_conflict,
    dismiss_conflict,
    get_conflict,
    list_conflicts,
    resolve_conflict,
    run_validation,
    validation_stats,
)

__all__ = [
    "ValidationError",
    "run_validation",
    "list_conflicts",
    "get_conflict",
    "confirm_conflict",
    "resolve_conflict",
    "dismiss_conflict",
    "validation_stats",
]
