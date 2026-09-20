"""Auth dependencies and RBAC enforcement (backend-enforced)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.config import get_settings
from app.database import get_db
from app.models import User, UserRole, UserStatus

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    id: str
    username: str
    role: str
    display_name: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value

    @property
    def is_reviewer(self) -> bool:
        return self.role in {UserRole.ADMIN.value, UserRole.REVIEWER.value}

    @property
    def is_analyst(self) -> bool:
        return self.role in {
            UserRole.ADMIN.value,
            UserRole.ANALYST.value,
            UserRole.REVIEWER.value,
        }


ROLE_PERMISSIONS: dict[str, set[str]] = {
    UserRole.ADMIN.value: {
        "users.manage",
        "documents.upload",
        "documents.delete",
        "documents.version",
        "documents.read",
        "review.act",
        "validation.act",
        "search",
        "explore",
        "analytics",
        "topics",
        "assistant",
        "reports.generate",
        "reports.read",
        "reports.delete",
        "audit.read",
        "settings.read",
        "system.configure",
    },
    UserRole.ANALYST.value: {
        "documents.upload",
        "documents.read",
        "review.act",
        "search",
        "explore",
        "analytics",
        "topics",
        "assistant",
        "reports.generate",
        "reports.read",
        "reports.delete",
        "settings.read",
    },
    UserRole.REVIEWER.value: {
        "documents.read",
        "review.act",
        "validation.act",
        "search",
        "explore",
        "settings.read",
        "reports.read",
    },
}


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def _load_user(db: Session, user_id: str) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def get_optional_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[AuthUser]:
    settings = get_settings()
    token = creds.credentials if creds else None
    if not token:
        # Dev convenience: optional X-Demo-User header when auth not required
        demo = request.headers.get("X-Demo-User")
        if demo and not settings.auth_required:
            u = db.query(User).filter(User.username == demo).first()
            if u and u.status == UserStatus.ACTIVE.value:
                return AuthUser(id=u.id, username=u.username, role=u.role, display_name=u.display_name)
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    user = _load_user(db, str(payload.get("sub") or ""))
    if not user or user.status != UserStatus.ACTIVE.value:
        return None
    return AuthUser(
        id=user.id,
        username=user.username,
        role=user.role,
        display_name=user.display_name,
    )


def get_current_user(
    user: Optional[AuthUser] = Depends(get_optional_user),
) -> AuthUser:
    settings = get_settings()
    if user:
        return user
    if not settings.auth_required:
        # Anonymous demo analyst when auth not strictly required
        return AuthUser(id="anonymous", username="ops.analyst", role=UserRole.ANALYST.value)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Sign in to continue.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_roles(*roles: str) -> Callable:
    allowed = set(roles)

    def _dep(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted for this action.",
            )
        return user

    return _dep


def require_permission(permission: str) -> Callable:
    def _dep(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not has_permission(user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return user

    return _dep
