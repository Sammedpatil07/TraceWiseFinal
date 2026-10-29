"""Unit tests for telemetry normalization and generic adapters.
"""

import pytest
from app.models.evidence import (
    NormalizedEvidence,
    EvidenceType,
    EvidenceSeverity,
    SourceType,
)
from app.ingestion.generic_adapter import (
    GenericLogAdapter,
    GenericMetricAdapter,
    GenericTraceAdapter,
    GenericDeploymentAdapter,
    GenericConfigAdapter,
)


def test_normalized_evidence_model():
    ev = NormalizedEvidence(
        id="ev-001",
        incident_id="inc-100",
        evidence_type=EvidenceType.LOG,
        service_id="order-service",
        timestamp="2026-10-28T12:00:00Z",
        summary="Test error log",
        details={"code": 500},
        severity=EvidenceSeverity.HIGH,
        anomaly_score=1.5,  # Should be clamped to 1.0
        source_type=SourceType.ORGANIZER,
    )

    assert ev.anomaly_score == 1.0
    assert ev.evidence_type == EvidenceType.LOG
    assert ev.severity == EvidenceSeverity.HIGH

    d = ev.to_dict()
    assert d["evidence_type"] == "LOG"
    assert d["source_type"] == "ORGANIZER"

    rebuilt = NormalizedEvidence.from_dict(d)
    assert rebuilt.id == "ev-001"
    assert rebuilt.details == {"code": 500}


def test_generic_log_adapter():
    adapter = GenericLogAdapter()
    raw = [
        {"service": "payment-service", "time": "2026-10-28T12:05:00Z", "level": "ERROR", "message": "NullPointerException in payment gateway"},
        {"service": "payment-service", "time": "2026-10-28T12:06:00Z", "level": "INFO", "message": "Heartbeat ok"},
    ]
    parsed = adapter.parse(raw, incident_id="inc-100")
    assert len(parsed) == 2
    assert parsed[0].evidence_type == EvidenceType.LOG
    assert parsed[0].severity == EvidenceSeverity.HIGH
    assert parsed[0].service_id == "payment-service"
    assert parsed[0].anomaly_score >= 0.7


def test_generic_metric_adapter():
    adapter = GenericMetricAdapter()
    raw = [
        {"service": "payment-service", "timestamp": "2026-10-28T12:05:00Z", "metric_name": "cpu_utilization", "value": 98.5, "threshold": 80.0, "z_score": 4.5}
    ]
    parsed = adapter.parse(raw, incident_id="inc-100")
    assert len(parsed) == 1
    assert parsed[0].evidence_type == EvidenceType.METRIC
    assert parsed[0].severity == EvidenceSeverity.CRITICAL
    assert parsed[0].anomaly_score > 0.8


def test_generic_trace_adapter():
    adapter = GenericTraceAdapter()
    raw = [
        {"service": "api-gateway", "timestamp": "2026-10-28T12:05:00Z", "endpoint": "/checkout", "http_status": 504, "duration_ms": 5000, "error": True}
    ]
    parsed = adapter.parse(raw, incident_id="inc-100")
    assert len(parsed) == 1
    assert parsed[0].evidence_type == EvidenceType.TRACE
    assert parsed[0].severity == EvidenceSeverity.CRITICAL


def test_generic_deployment_and_config_adapter():
    dep_adapter = GenericDeploymentAdapter()
    raw_dep = [{"service": "auth-service", "timestamp": "2026-10-28T11:59:00Z", "commit_hash": "a1b2c3d"}]
    parsed_dep = dep_adapter.parse(raw_dep, incident_id="inc-100")
    assert len(parsed_dep) == 1
    assert parsed_dep[0].evidence_type == EvidenceType.DEPLOYMENT

    cfg_adapter = GenericConfigAdapter()
    raw_cfg = [{"service": "auth-service", "timestamp": "2026-10-28T11:58:00Z", "key": "jwt_expiry", "previous_value": "1h", "new_value": "1m"}]
    parsed_cfg = cfg_adapter.parse(raw_cfg, incident_id="inc-100")
    assert len(parsed_cfg) == 1
    assert parsed_cfg[0].evidence_type == EvidenceType.CONFIGURATION
