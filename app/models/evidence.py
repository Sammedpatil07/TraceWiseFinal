"""Normalized Internal Evidence Model for AO-03.

Supports:
- LOG
- METRIC
- TRACE
- DEPLOYMENT
- CONFIGURATION
- DEPENDENCY

Deterministic source of truth for all downstream Root Cause Analysis.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List


class EvidenceType(str, Enum):
    LOG = "LOG"
    METRIC = "METRIC"
    TRACE = "TRACE"
    DEPLOYMENT = "DEPLOYMENT"
    CONFIGURATION = "CONFIGURATION"
    DEPENDENCY = "DEPENDENCY"


class EvidenceSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class SourceType(str, Enum):
    ORGANIZER = "ORGANIZER"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"


@dataclass
class NormalizedEvidence:
    id: str
    incident_id: str
    evidence_type: EvidenceType = EvidenceType.LOG
    service: str = ""
    timestamp: str = ""  # ISO-8601 string: YYYY-MM-DDTHH:MM:SSZ
    severity: EvidenceSeverity = EvidenceSeverity.INFO
    event_type: str = ""
    message: str = ""
    summary: str = ""

    # Specific Telemetry Linkages
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    request_id: Optional[str] = None
    deployment_id: Optional[str] = None
    configuration_id: Optional[str] = None

    # Metric Specifics
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None

    # Provenance & Audit
    source_type: SourceType = SourceType.ORGANIZER
    source_file: Optional[str] = None
    source_record: Optional[Dict[str, Any]] = None
    redacted: bool = False

    # Scoring & Metadata
    anomaly_score: float = 0.0  # 0.0 to 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    # Backward compatibility constructor helper
    service_id_alias: Optional[str] = None

    def __init__(
        self,
        id: str,
        incident_id: str,
        evidence_type: EvidenceType = EvidenceType.LOG,
        service: str = "",
        timestamp: str = "",
        severity: EvidenceSeverity = EvidenceSeverity.INFO,
        event_type: str = "",
        message: str = "",
        summary: str = "",
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        request_id: Optional[str] = None,
        deployment_id: Optional[str] = None,
        configuration_id: Optional[str] = None,
        metric_name: Optional[str] = None,
        metric_value: Optional[float] = None,
        source_type: SourceType = SourceType.ORGANIZER,
        source_file: Optional[str] = None,
        source_record: Optional[Dict[str, Any]] = None,
        redacted: bool = False,
        anomaly_score: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
        service_id: Optional[str] = None,
        **kwargs: Any,
    ):
        self.id = str(id)
        self.incident_id = str(incident_id)

        # Handle evidence type
        if isinstance(evidence_type, str):
            self.evidence_type = EvidenceType(evidence_type.upper())
        else:
            self.evidence_type = evidence_type

        # Handle service / service_id
        self.service = service or service_id or kwargs.get("service_id", "") or "unknown-service"

        # Timestamp
        self.timestamp = str(timestamp)

        # Severity
        if isinstance(severity, str):
            self.severity = EvidenceSeverity(severity.upper())
        else:
            self.severity = severity

        # Event type & summary/message sync
        self.event_type = event_type or self.evidence_type.value
        self.summary = summary or message or kwargs.get("summary", "") or "Evidence record"
        self.message = message or self.summary

        # Specific IDs
        self.trace_id = trace_id or kwargs.get("traceId") or (details.get("trace_id") if details else None)
        self.span_id = span_id or kwargs.get("spanId") or (details.get("span_id") if details else None)
        self.parent_span_id = parent_span_id or kwargs.get("parentSpanId") or (details.get("parent_span_id") if details else None)
        self.request_id = request_id or kwargs.get("requestId") or (details.get("request_id") if details else None)
        self.deployment_id = deployment_id or (details.get("deployment_id") if details else None)
        self.configuration_id = configuration_id or (details.get("configuration_id") if details else None)

        # Metric values
        self.metric_name = metric_name or (details.get("metric_name") if details else None)
        self.metric_value = metric_value if metric_value is not None else (details.get("value") if details else None)

        # Provenance
        if isinstance(source_type, str):
            self.source_type = SourceType(source_type.upper())
        else:
            self.source_type = source_type
        self.source_file = source_file
        self.source_record = source_record
        self.redacted = bool(redacted)

        # Anomaly score clamped between 0.0 and 1.0
        try:
            self.anomaly_score = max(0.0, min(1.0, float(anomaly_score)))
        except (ValueError, TypeError):
            self.anomaly_score = 0.0

        # Sync details & metadata
        self.metadata = dict(metadata or {})
        self.details = dict(details or {})
        if self.metadata and not self.details:
            self.details = dict(self.metadata)
        elif self.details and not self.metadata:
            self.metadata = dict(self.details)

        # Preserve any additional kwargs in details
        for k, v in kwargs.items():
            if k not in ["service_id", "summary"]:
                self.details[k] = v

    @property
    def service_id(self) -> str:
        """Backward-compatible alias for service."""
        return self.service

    @service_id.setter
    def service_id(self, val: str):
        self.service = val

    @property
    def parsed_time(self) -> datetime:
        """Parse timestamp to datetime object in UTC."""
        ts = self.timestamp.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary suitable for JSON serialization and DB storage."""
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "evidence_type": self.evidence_type.value,
            "service": self.service,
            "service_id": self.service,  # backward compatibility
            "timestamp": self.timestamp,
            "severity": self.severity.value,
            "event_type": self.event_type,
            "message": self.message,
            "summary": self.summary,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "request_id": self.request_id,
            "deployment_id": self.deployment_id,
            "configuration_id": self.configuration_id,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "source_type": self.source_type.value,
            "source_file": self.source_file,
            "source_record": self.source_record,
            "redacted": self.redacted,
            "anomaly_score": self.anomaly_score,
            "metadata": self.metadata,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NormalizedEvidence:
        """Construct from raw dictionary."""
        return cls(
            id=str(data["id"]),
            incident_id=str(data["incident_id"]),
            evidence_type=EvidenceType(data.get("evidence_type", "LOG")),
            service=str(data.get("service") or data.get("service_id", "unknown-service")),
            timestamp=str(data.get("timestamp", "")),
            severity=EvidenceSeverity(data.get("severity", "INFO")),
            event_type=str(data.get("event_type", "")),
            message=str(data.get("message") or data.get("summary", "")),
            summary=str(data.get("summary") or data.get("message", "Evidence record")),
            trace_id=data.get("trace_id"),
            span_id=data.get("span_id"),
            parent_span_id=data.get("parent_span_id"),
            request_id=data.get("request_id"),
            deployment_id=data.get("deployment_id"),
            configuration_id=data.get("configuration_id"),
            metric_name=data.get("metric_name"),
            metric_value=data.get("metric_value"),
            source_type=SourceType(data.get("source_type", "ORGANIZER")),
            source_file=data.get("source_file"),
            source_record=data.get("source_record"),
            redacted=bool(data.get("redacted", False)),
            anomaly_score=float(data.get("anomaly_score", 0.0)),
            metadata=dict(data.get("metadata", {})),
            details=dict(data.get("details", {})),
        )


@dataclass
class EvidenceCorrelation:
    """Explicit correlation link between two pieces of evidence."""
    source_evidence_id: str
    target_evidence_id: str
    relation_type: str  # TIME_PROXIMITY, SAME_SERVICE, SAME_TRACE, TRACE_PARENT_CHILD, DEPENDENCY, ERROR_EVENT, DEPLOYMENT_PROXIMITY, CONFIG_PROXIMITY, METRIC_ANOMALY
    reason: str
    score: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ServiceNode:
    id: str
    name: str
    tier: str = "service"
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ServiceDependency:
    id: str
    source_service: str
    target_service: str
    call_type: str = "HTTP"
    critical: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
