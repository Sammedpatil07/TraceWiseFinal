"""Security audit logging helper for TraceWise AO-03.
"""

from typing import Optional, Dict, Any
from app.models.audit import AuditLog, AuditAction
from app.models.user import User
from app.auth.session import get_current_user
from app.storage import get_storage


SENSITIVE_FIELD_NAMES = {"password", "secret", "token", "key", "authorization", "bearer", "pwd"}


def sanitize_metadata(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not meta:
        return {}
    clean: Dict[str, Any] = {}
    for k, v in meta.items():
        if any(s in k.lower() for s in SENSITIVE_FIELD_NAMES):
            clean[k] = "[REDACTED]"
        elif isinstance(v, dict):
            clean[k] = sanitize_metadata(v)
        else:
            clean[k] = str(v)[:250] if not isinstance(v, (int, float, bool)) else v
    return clean


def log_audit_event(
    action: str,
    resource_type: str = "SYSTEM",
    resource_id: Optional[str] = None,
    result: str = "SUCCESS",
    metadata: Optional[Dict[str, Any]] = None,
    user: Optional[User] = None,
) -> None:
    """Records an immutable security audit event into storage."""
    try:
        active_user = user or get_current_user()
        user_id = active_user.id if active_user else "anonymous"
        username = active_user.username if active_user else "anonymous"
        role = active_user.role if active_user else "ANONYMOUS"

        entry = AuditLog(
            user_id=user_id,
            username=username,
            role=role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            metadata=sanitize_metadata(metadata),
        )

        storage = get_storage()
        storage.save_audit_log(entry)
    except Exception as e:
        # Never crash the main execution flow if audit logging encounters a database glitch
        import logging
        logging.getLogger(__name__).error(f"Audit log failure: {e}")
