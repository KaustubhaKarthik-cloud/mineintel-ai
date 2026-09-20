"""Seed default users and auth bootstrap."""

from __future__ import annotations

from sqlalchemy.orm import Session

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
        "username": "analyst",
        "display_name": "Ops Analyst",
        "password": "analyst123",
        "role": UserRole.ANALYST.value,
    },
    {
        "username": "reviewer",
        "display_name": "Data Reviewer",
        "password": "reviewer123",
        "role": UserRole.REVIEWER.value,
    },
]


def seed_default_users(db: Session) -> int:
    """Create default demo users if the users table is empty. Returns created count."""
    if db.query(User).count() > 0:
        return 0
    created = 0
    for spec in DEFAULT_USERS:
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
    db.commit()
    return created
