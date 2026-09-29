"""Admin user management APIs."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import AuthUser, normalize_role, require_permission
from app.auth.security import hash_password
from app.database import get_db
from app.models import User, UserRole, UserStatus
from app.services.audit import write_audit

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=128)
    role: str = Field(default=UserRole.USER.value)


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=128)
    role: Optional[str] = None
    status: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


def _public(u: User) -> dict[str, Any]:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "status": u.status,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def _validate_role(role: str) -> str:
    canon = normalize_role(role)
    # Only accept canonical roles for new/updated accounts (no legacy create)
    if canon not in {UserRole.ADMIN.value, UserRole.USER.value}:
        raise HTTPException(
            status_code=400,
            detail="Invalid role. Allowed: admin, user",
        )
    return canon


def _validate_status(st: str) -> str:
    allowed = {s.value for s in UserStatus}
    if st not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {sorted(allowed)}")
    return st


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("users.manage")),
) -> dict[str, Any]:
    rows = db.query(User).order_by(User.created_at.desc()).all()
    return {"total": len(rows), "items": [_public(u) for u in rows]}


@router.post("")
def create_user(
    body: CreateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_permission("users.manage")),
) -> dict[str, Any]:
    username = body.username.strip().lower()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    role = _validate_role(body.role)
    row = User(
        username=username,
        display_name=body.display_name or username,
        password_hash=hash_password(body.password),
        role=role,
        status=UserStatus.ACTIVE.value,
    )
    db.add(row)
    db.flush()
    write_audit(
        db,
        action="USER_CREATED",
        actor=actor.username,
        entity_type="user",
        entity_id=row.id,
        details={"username": username, "role": role},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    return _public(row)


@router.patch("/{user_id}")
def update_user(
    user_id: str,
    body: UpdateUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: AuthUser = Depends(require_permission("users.manage")),
) -> dict[str, Any]:
    row = db.query(User).filter(User.id == user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    changes: dict[str, Any] = {}
    if body.display_name is not None:
        row.display_name = body.display_name
        changes["display_name"] = body.display_name
    if body.role is not None:
        row.role = _validate_role(body.role)
        changes["role"] = row.role
    if body.status is not None:
        if row.id == actor.id and body.status == UserStatus.DISABLED.value:
            raise HTTPException(status_code=400, detail="Cannot disable your own account")
        row.status = _validate_status(body.status)
        changes["status"] = row.status
    if body.password:
        row.password_hash = hash_password(body.password)
        changes["password"] = "updated"
    write_audit(
        db,
        action="USER_UPDATED",
        actor=actor.username,
        entity_type="user",
        entity_id=row.id,
        details=changes,
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    return _public(row)
