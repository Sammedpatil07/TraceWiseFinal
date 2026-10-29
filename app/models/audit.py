"""Security Audit Log model for AO-03.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import uuid


class AuditAction:
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    FAILED_LOGIN = "FAILED_LOGIN"
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"
    VIEW_INCIDENT = "VIEW_INCIDENT"
    RUN_RCA = "RUN_RCA"
    VIEW_EVIDENCE = "VIEW_EVIDENCE"
    RESTRICTED_EVIDENCE_ACCESS = "RESTRICTED_EVIDENCE_ACCESS"
    CREATE_USER = "CREATE_USER"
    UPDATE_ROLE = "UPDATE_ROLE"
    TOGGLE_USER_STATUS = "TOGGLE_USER_STATUS"
    INGEST_TELEMETRY = "INGEST_TELEMETRY"
    DEMO_ACTION = "DEMO_ACTION"


@dataclass
class AuditLog:
    id: str = field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:12]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    user_id: str = "anonymous"
    username: str = "anonymous"
    role: str = "ANONYMOUS"
    action: str = AuditAction.LOGIN
    resource_type: str = "SYSTEM"
    resource_id: Optional[str] = None
    result: str = "SUCCESS"  # SUCCESS, DENIED, FAILURE
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "result": self.result,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditLog":
        return cls(
            id=str(data.get("id", f"aud_{uuid.uuid4().hex[:12]}")),
            timestamp=str(data.get("timestamp") or datetime.utcnow().isoformat() + "Z"),
            user_id=str(data.get("user_id", "anonymous")),
            username=str(data.get("username", "anonymous")),
            role=str(data.get("role", "ANONYMOUS")),
            action=str(data.get("action", AuditAction.LOGIN)),
            resource_type=str(data.get("resource_type", "SYSTEM")),
            resource_id=data.get("resource_id"),
            result=str(data.get("result", "SUCCESS")),
            metadata=dict(data.get("metadata") or {}),
        )
