"""Authentication and current-user endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import ROLE_PERMISSIONS, AuthUser, get_current_user, get_optional_user, normalize_role
from app.auth.security import create_access_token, verify_password
from app.config import get_settings
from app.database import get_db
from app.models import User, UserRole, UserStatus
from app.services.audit import write_audit

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


def _user_public(u: User) -> dict[str, Any]:
    role = normalize_role(u.role)
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": role,
        "status": u.status,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "permissions": sorted(ROLE_PERMISSIONS.get(role, set())),
    }


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.username == body.username.strip()).first()
    if not user or not verify_password(body.password, user.password_hash):
        write_audit(
            db,
            action="LOGIN_FAILED",
            actor=body.username.strip(),
            entity_type="user",
            details={"reason": "invalid_credentials"},
            ip_address=request.client.host if request.client else None,
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if user.status != UserStatus.ACTIVE.value:
        write_audit(
            db,
            action="LOGIN_FAILED",
            actor=user.username,
            entity_type="user",
            entity_id=user.id,
            details={"reason": "disabled"},
            ip_address=request.client.host if request.client else None,
            commit=True,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled")

    user.last_login_at = datetime.now(timezone.utc)
    role = normalize_role(user.role)
    if user.role != role:
        user.role = role
    token = create_access_token(user_id=user.id, username=user.username, role=role)
    write_audit(
        db,
        action="LOGIN",
        actor=user.username,
        entity_type="user",
        entity_id=user.id,
        details={"role": role},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    return LoginResponse(access_token=token, user=_user_public(user))


@router.get("/me")
def me(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> dict[str, Any]:
    settings = get_settings()
    if user.id == "anonymous":
        return {
            "id": "anonymous",
            "username": user.username,
            "display_name": user.display_name or "Anonymous User",
            "role": UserRole.USER.value,
            "status": "active",
            "auth_required": settings.auth_required,
            "anonymous": True,
            "permissions": sorted(ROLE_PERMISSIONS.get(UserRole.USER.value, set())),
        }
    row = db.query(User).filter(User.id == user.id).first()
    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    out = _user_public(row)
    out["auth_required"] = settings.auth_required
    out["anonymous"] = False
    return out


@router.post("/logout")
def logout(
    request: Request,
    user: Optional[AuthUser] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if user:
        write_audit(
            db,
            action="LOGOUT",
            actor=user.username,
            entity_type="user",
            entity_id=user.id if user.id != "anonymous" else None,
            ip_address=request.client.host if request.client else None,
            commit=True,
        )
    return {"status": "ok"}
