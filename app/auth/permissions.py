"""Permission matrix definition for TraceWise AO-03.
"""

from typing import Dict, Any, Optional
from app.models.user import User, UserRole


PERMISSION_MATRIX: Dict[str, Dict[str, bool]] = {
    UserRole.ADMIN: {
        "view_dashboard": True,
        "view_incidents": True,
        "run_rca": True,
        "view_investigation": True,
        "view_evidence": True,
        "view_raw_telemetry": True,
        "view_timeline": True,
        "view_service_graph": True,
        "view_evaluation": True,
        "ingest_telemetry": True,
        "manage_users": True,
        "manage_roles": True,
        "view_audit_logs": True,
        "manage_demo_data": True,
    },
    UserRole.INCIDENT_RESPONDER: {
        "view_dashboard": True,
        "view_incidents": True,
        "run_rca": True,
        "view_investigation": True,
        "view_evidence": True,
        "view_raw_telemetry": True,
        "view_timeline": True,
        "view_service_graph": True,
        "view_evaluation": True,
        "ingest_telemetry": False,
        "manage_users": False,
        "manage_roles": False,
        "view_audit_logs": True,  # Limited to investigation history
        "manage_demo_data": False,
    },
    UserRole.VIEWER: {
        "view_dashboard": True,
        "view_incidents": True,
        "run_rca": False,  # Read-only RCA
        "view_investigation": True,
        "view_evidence": True,  # Sanitized/high-level only
        "view_raw_telemetry": False,  # Restricted
        "view_timeline": True,
        "view_service_graph": True,
        "view_evaluation": True,
        "ingest_telemetry": False,
        "manage_users": False,
        "manage_roles": False,
        "view_audit_logs": False,
        "manage_demo_data": False,
    },
}


def has_permission(user: Optional[User], permission: str) -> bool:
    if not user or not user.is_active:
        return False
    role = UserRole.normalize(user.role)
    perms = PERMISSION_MATRIX.get(role, {})
    return perms.get(permission, False)
