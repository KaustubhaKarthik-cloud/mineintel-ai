"""Auth dependencies and RBAC enforcement (backend-enforced).

SIH hackathon model: exactly two active roles — USER and ADMIN.
Legacy roles analyst/reviewer are normalized at permission-check time
(analyst→user, reviewer→admin) and migrated in the database on startup.
"""

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

# Canonical permissions
_USER_PERMS: set[str] = {
    "documents.upload",
    "documents.read",
    "search",
    "explore",
    "analytics",
    "topics",
    "assistant",
    "reports.read",
    "reports.generate",
    "settings.read",
}

_ADMIN_PERMS: set[str] = {
    *_USER_PERMS,
    "users.manage",
    "documents.delete",
    "documents.version",
    "review.act",
    "validation.act",
    "reports.generate",
    "reports.delete",
    "audit.read",
    "system.configure",
}


def normalize_role(role: Optional[str]) -> str:
    """Map legacy roles to the two-role model. Unknown → user (least privilege)."""
    r = (role or "").strip().lower()
    if r == UserRole.ADMIN.value or r == "reviewer":
        return UserRole.ADMIN.value
    if r == UserRole.USER.value or r == "analyst":
        return UserRole.USER.value
    if r in {"admin"}:
        return UserRole.ADMIN.value
    return UserRole.USER.value


ROLE_PERMISSIONS: dict[str, set[str]] = {
    UserRole.ADMIN.value: set(_ADMIN_PERMS),
    UserRole.USER.value: set(_USER_PERMS),
    # Legacy keys kept so old JWT/DB strings still resolve until migration completes
    "analyst": set(_USER_PERMS),
    "reviewer": set(_ADMIN_PERMS),
}


@dataclass
class AuthUser:
    id: str
    username: str
    role: str
    display_name: Optional[str] = None

    @property
    def canonical_role(self) -> str:
        return normalize_role(self.role)

    @property
    def is_admin(self) -> bool:
        return self.canonical_role == UserRole.ADMIN.value

    @property
    def is_reviewer(self) -> bool:
        """Deprecated alias — review capability is admin-only."""
        return self.is_admin

    @property
    def is_analyst(self) -> bool:
        """Deprecated alias — any authenticated app user."""
        return self.canonical_role in {UserRole.ADMIN.value, UserRole.USER.value}


def has_permission(role: str, permission: str) -> bool:
    canon = normalize_role(role)
    return permission in ROLE_PERMISSIONS.get(canon, set())


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
        demo = request.headers.get("X-Demo-User")
        if demo and not settings.auth_required:
            u = db.query(User).filter(User.username == demo).first()
            if u and u.status == UserStatus.ACTIVE.value:
                return AuthUser(
                    id=u.id,
                    username=u.username,
                    role=normalize_role(u.role),
                    display_name=u.display_name,
                )
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
        role=normalize_role(user.role),
        display_name=user.display_name,
    )


def get_current_user(
    user: Optional[AuthUser] = Depends(get_optional_user),
) -> AuthUser:
    settings = get_settings()
    if user:
        return user
    if not settings.auth_required:
        # Least-privilege anonymous USER — never review/validation/admin.
        return AuthUser(
            id="anonymous",
            username="anonymous",
            role=UserRole.USER.value,
            display_name="Anonymous User",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Sign in to continue.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_roles(*roles: str) -> Callable:
    allowed = {normalize_role(r) for r in roles}

    def _dep(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.canonical_role not in allowed:
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
