"""Authentication and RBAC route decorators for TraceWise AO-03.
"""

from functools import wraps
from typing import Any, Callable
from flask import request, jsonify
from app.models.user import UserRole
from app.models.audit import AuditAction
from app.auth.session import get_current_user
from app.auth.audit import log_audit_event


def login_required(f: Callable) -> Callable:
    """Decorator ensuring request originates from an authenticated user."""
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        user = get_current_user()
        if not user:
            return jsonify({
                "error": "Authentication required. Please log in.",
                "code": "UNAUTHORIZED",
            }), 401
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles: str) -> Callable:
    """Decorator enforcing Role-Based Access Control (RBAC) at Flask route level."""
    normalized_roles = [UserRole.normalize(r) for r in allowed_roles]

    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            user = get_current_user()
            if not user:
                return jsonify({
                    "error": "Authentication required. Please log in.",
                    "code": "UNAUTHORIZED",
                }), 401

            if user.role not in normalized_roles:
                # Log unauthorized access attempt in security audit log
                log_audit_event(
                    action=AuditAction.UNAUTHORIZED_ACCESS,
                    resource_type="API_ROUTE",
                    resource_id=request.path,
                    result="DENIED",
                    metadata={
                        "endpoint": request.endpoint,
                        "method": request.method,
                        "required_roles": normalized_roles,
                        "user_role": user.role,
                    },
                    user=user,
                )
                return jsonify({
                    "error": "Forbidden: Insufficient permissions for this resource.",
                    "required_roles": normalized_roles,
                    "current_role": user.role,
                    "code": "FORBIDDEN",
                }), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator
