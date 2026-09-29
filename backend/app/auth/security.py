"""Password hashing and JWT helpers (Phase 7 auth)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt

from app.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def create_access_token(*, user_id: str, username: str, role: str) -> str:
    settings = get_settings()
    expire_hours = getattr(settings, "jwt_expire_hours", 24) or 24
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=int(expire_hours)),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
