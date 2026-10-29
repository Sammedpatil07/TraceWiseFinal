"""Auth and RBAC package for TraceWise AO-03.
"""

from app.auth.session import login_user, logout_user, get_current_user
from app.auth.decorators import login_required, role_required
from app.auth.audit import log_audit_event
from app.auth.permissions import PERMISSION_MATRIX, has_permission

__all__ = [
    "login_user",
    "logout_user",
    "get_current_user",
    "login_required",
    "role_required",
    "log_audit_event",
    "PERMISSION_MATRIX",
    "has_permission",
]
