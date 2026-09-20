"""Centralized audit logging (immutable append-only for normal users)."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog

# Keys that must never be persisted in audit details
_SENSITIVE = {"password", "password_hash", "token", "api_key", "secret", "authorization"}


def _sanitize(details: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not details:
        return None
    out: dict[str, Any] = {}
    for k, v in details.items():
        if str(k).lower() in _SENSITIVE:
            continue
        if isinstance(v, dict):
            out[k] = _sanitize(v)
        else:
            out[k] = v
    return out


def write_audit(
    db: Session,
    *,
    action: str,
    actor: Optional[str],
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    commit: bool = False,
) -> AuditLog:
    row = AuditLog(
        action=action,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        details=_sanitize(details),
        ip_address=ip_address,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row
