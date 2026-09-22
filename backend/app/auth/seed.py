"""Seed default users and migrate legacy roles → user/admin."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.deps import normalize_role
from app.auth.security import hash_password
from app.models import User, UserRole, UserStatus

DEFAULT_USERS = [
    {
        "username": "admin",
        "display_name": "System Admin",
        "password": "admin123",
        "role": UserRole.ADMIN.value,
    },
    {
        "username": "user",
        "display_name": "Standard User",
        "password": "user123",
        "role": UserRole.USER.value,
    },
]


def migrate_legacy_roles(db: Session) -> int:
    """Remap analyst→user, reviewer→admin. Never deletes users or resets passwords."""
    updated = 0
    for row in db.query(User).all():
        canon = normalize_role(row.role)
        if row.role != canon:
            row.role = canon
            db.add(row)
            updated += 1
    if updated:
        db.commit()
    return updated


def seed_default_users(db: Session) -> int:
    """Create default demo users if missing. Migrates legacy roles always."""
    migrate_legacy_roles(db)
    created = 0
    for spec in DEFAULT_USERS:
        existing = db.query(User).filter(User.username == spec["username"]).first()
        if existing:
            # Ensure role is canonical for seed accounts
            if existing.role != spec["role"]:
                existing.role = spec["role"]
                db.add(existing)
            continue
        db.add(
            User(
                username=spec["username"],
                display_name=spec["display_name"],
                password_hash=hash_password(spec["password"]),
                role=spec["role"],
                status=UserStatus.ACTIVE.value,
            )
        )
        created += 1
    if created:
        db.commit()
    else:
        db.commit()  # persist any role remaps on seed accounts
    return created
