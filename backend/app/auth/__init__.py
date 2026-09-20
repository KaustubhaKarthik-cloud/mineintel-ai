"""Phase 7 auth package."""

from app.auth.deps import AuthUser, get_current_user, get_optional_user, require_permission, require_roles
from app.auth.seed import seed_default_users

__all__ = [
    "AuthUser",
    "get_current_user",
    "get_optional_user",
    "require_permission",
    "require_roles",
    "seed_default_users",
]
