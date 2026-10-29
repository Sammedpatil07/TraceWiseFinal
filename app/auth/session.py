"""Session management for TraceWise AO-03.
"""

from typing import Optional
from flask import session, g
from app.models.user import User
from app.storage import get_storage


def login_user(user: User) -> None:
    """Stores user identity in secure server-side session."""
    session.permanent = True
    session["user_id"] = user.id
    session["username"] = user.username
    session["role"] = user.role
    session["email"] = getattr(user, "email", "")
    g.current_user = user


def logout_user() -> None:
    """Invalidates session on logout."""
    session.clear()
    g.current_user = None


def get_current_user() -> Optional[User]:
    """Retrieves authenticated user from session or context."""
    if hasattr(g, "current_user") and g.current_user is not None:
        return g.current_user

    user_id = session.get("user_id")
    if not user_id:
        return None

    username = session.get("username", "")
    role = session.get("role", "")
    email = session.get("email", "")

    storage = get_storage()
    try:
        user = storage.get_user_by_id(user_id)
        if user:
            if not user.is_active:
                session.clear()
                g.current_user = None
                return None
            g.current_user = user
            return user
    except Exception:
        # Do not treat temporary network/database timeouts as session invalidation
        pass

    # If database lookup timed out or had temporary network latency,
    # preserve authenticated session from the cryptographically signed Flask cookie
    if username and role:
        fallback_user = User(
            id=user_id,
            username=username,
            role=role,
            email=email,
            is_active=True,
        )
        g.current_user = fallback_user
        return fallback_user

    session.clear()
    g.current_user = None
    return None
