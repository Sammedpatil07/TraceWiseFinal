"""Comprehensive Deterministic Test Suite for AO-03 Scenarios.

Implements all 9 required hackathon test scenarios:
TEST 1: Deployment shortly before errors -> Deployment becomes strong candidate.
TEST 2: Downstream service fails first -> Downstream failure receives stronger evidence score.
TEST 3: Configuration change precedes the incident -> Configuration becomes candidate.
TEST 4: Metric anomaly co-occurs with logs/errors -> Correlation is visible.
TEST 5: No meaningful evidence exists -> Returns UNKNOWN / INSUFFICIENT EVIDENCE.
TEST 6: Conflicting evidence exists -> Does not pretend certainty.
TEST 7: Invalid evidence ID supplied -> Validator rejects it.
TEST 8: Duplicate evidence records exist -> Handled safely.
TEST 9: Malformed input record exists -> Ingestion reports error without crashing batch.
"""

import pytest
from app.models.evidence import (
    NormalizedEvidence,
    EvidenceType,
    EvidenceSeverity,
    SourceType,
    ServiceNode,
    ServiceDependency,
)
from app.models.incident import Incident
from app.storage.sqlite_adapter import SqliteStorage
from app.engine.dependency_graph import DependencyGraphManager
from app.engine.correlation import CorrelationEngine
from app.engine.validator import EvidenceValidator
from app.engine.rca_engine import RCAEngine
from app.ingestion.generic_adapter import GenericTelemetryIngestor


@pytest.fixture
def clean_storage(tmp_path):
    db_path = str(tmp_path / "test_scenarios.db")
    storage = SqliteStorage(db_path)
    return storage


# =============================================================================
# TEST 1: Deployment shortly before errors -> Strong candidate
# =============================================================================
def test_1_deployment_preceding_errors_is_strong_candidate(clean_storage):
    svc = ServiceNode(id="checkout-service", name="Checkout Service")
    clean_storage.save_service(svc)

    incident = Incident(
        id="INC-TEST-1",
        title="Post-deployment checkout crash",
        affected_services=["checkout-service"],
        started_at="2026-10-28T10:00:00Z",
    )
    clean_storage.save_incident(incident)

    evidence = [
        NormalizedEvidence(
            id="EVID-DEP-1",
            incident_id="INC-TEST-1",
            evidence_type=EvidenceType.DEPLOYMENT,
            service="checkout-service",
            timestamp="2026-10-28T10:01:00Z",
            summary="Deployment v3.0.0 applied to checkout-service",
            deployment_id="deploy-v3.0.0",
            anomaly_score=0.88,
        ),
        NormalizedEvidence(
            id="EVID-ERR-1",
            incident_id="INC-TEST-1",
            evidence_type=EvidenceType.LOG,
            service="checkout-service",
            timestamp="2026-10-28T10:03:00Z",
            summary="NullPointerException in checkout payment workflow",
            severity=EvidenceSeverity.CRITICAL,
            anomaly_score=0.92,
        ),
        NormalizedEvidence(
            id="EVID-ERR-2",
            incident_id="INC-TEST-1",
            evidence_type=EvidenceType.LOG,
            service="checkout-service",
            timestamp="2026-10-28T10:04:00Z",
            summary="HTTP 500 Internal Server Error returned to users",
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.85,
        ),
    ]
    clean_storage.save_evidence_batch(evidence)

    engine = RCAEngine(clean_storage)
    result = engine.run_rca("INC-TEST-1", trigger_llm=False)

    assert result.status == "SUCCESS"
    assert result.top_candidate is not None
    assert result.top_candidate.service_id == "checkout-service"
    assert result.top_candidate.candidate_type == "DEPLOYMENT_FAULT"
    assert result.top_candidate.evidence_score >= 0.50
    assert "EVID-DEP-1" in result.top_candidate.supporting_evidence_ids


# =============================================================================
# TEST 2: Downstream service fails first -> Downstream scores higher
# =============================================================================
def test_2_downstream_dependency_failure_scores_higher_than_upstream(clean_storage):
    gw = ServiceNode(id="api-gateway", name="Gateway", tier="ingress")
    auth = ServiceNode(id="auth-service", name="Auth", tier="core")
    clean_storage.save_service(gw)
    clean_storage.save_service(auth)

    dep = ServiceDependency(id="d1", source_service="api-gateway", target_service="auth-service")
    clean_storage.save_dependency(dep)

    incident = Incident(
        id="INC-TEST-2",
        title="Gateway authentication failure cascade",
        affected_services=["api-gateway", "auth-service"],
        started_at="2026-10-28T09:00:00Z",
    )
    clean_storage.save_incident(incident)

    evidence = [
        # Downstream auth-service fails first at 09:01
        NormalizedEvidence(
            id="EVID-AUTH-1",
            incident_id="INC-TEST-2",
            evidence_type=EvidenceType.LOG,
            service="auth-service",
            timestamp="2026-10-28T09:01:00Z",
            summary="DatabaseDeadlock: Auth sessions table locked",
            severity=EvidenceSeverity.CRITICAL,
            anomaly_score=0.95,
        ),
        NormalizedEvidence(
            id="EVID-AUTH-2",
            incident_id="INC-TEST-2",
            evidence_type=EvidenceType.METRIC,
            service="auth-service",
            timestamp="2026-10-28T09:02:00Z",
            summary="auth_response_time_ms spiked to 9000ms",
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.90,
        ),
        # Upstream gateway begins showing errors afterward at 09:06
        NormalizedEvidence(
            id="EVID-GW-1",
            incident_id="INC-TEST-2",
            evidence_type=EvidenceType.LOG,
            service="api-gateway",
            timestamp="2026-10-28T09:06:00Z",
            summary="Gateway timeout waiting for auth-service response",
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.75,
        ),
    ]
    clean_storage.save_evidence_batch(evidence)

    engine = RCAEngine(clean_storage)
    result = engine.run_rca("INC-TEST-2", trigger_llm=False)

    assert result.status == "SUCCESS"
    assert result.top_candidate.service_id == "auth-service"
    # Find gateway rank
    gw_cand = next(c for c in result.ranked_candidates if c.service_id == "api-gateway")
    assert result.top_candidate.evidence_score > gw_cand.evidence_score


# =============================================================================
# TEST 3: Configuration change precedes incident -> Candidate
# =============================================================================
def test_3_configuration_change_preceding_incident_becomes_candidate(clean_storage):
    svc = ServiceNode(id="payment-service", name="Payment Service")
    clean_storage.save_service(svc)

    incident = Incident(
        id="INC-TEST-3",
        title="Payment timeouts after config update",
        affected_services=["payment-service"],
        started_at="2026-10-28T14:00:00Z",
    )
    clean_storage.save_incident(incident)

    evidence = [
        NormalizedEvidence(
            id="EVID-CFG-1",
            incident_id="INC-TEST-3",
            evidence_type=EvidenceType.CONFIGURATION,
            service="payment-service",
            timestamp="2026-10-28T14:01:00Z",
            summary="Configuration update: 'db.max_connections' changed from 50 to 5",
            configuration_id="cfg-pool-01",
            anomaly_score=0.90,
        ),
        NormalizedEvidence(
            id="EVID-ERR-POOL",
            incident_id="INC-TEST-3",
            evidence_type=EvidenceType.LOG,
            service="payment-service",
            timestamp="2026-10-28T14:04:00Z",
            summary="ConnectionPoolTimeoutException: pool exhausted",
            severity=EvidenceSeverity.CRITICAL,
            anomaly_score=0.93,
        ),
    ]
    clean_storage.save_evidence_batch(evidence)

    engine = RCAEngine(clean_storage)
    result = engine.run_rca("INC-TEST-3", trigger_llm=False)

    assert result.status == "SUCCESS"
    assert result.top_candidate.service_id == "payment-service"
    assert result.top_candidate.candidate_type == "CONFIG_DRIFT"
    assert "EVID-CFG-1" in result.top_candidate.supporting_evidence_ids


# =============================================================================
# TEST 4: Metric anomaly co-occurs with logs/errors -> Correlation visible
# =============================================================================
def test_4_metric_anomaly_and_logs_correlation_visible(clean_storage):
    svc = ServiceNode(id="cache-service", name="Cache")
    clean_storage.save_service(svc)
    graph = DependencyGraphManager([svc], [])
    correlation_engine = CorrelationEngine(graph)

    e_metric = NormalizedEvidence(
        id="EVID-M1",
        incident_id="INC-TEST-4",
        evidence_type=EvidenceType.METRIC,
        service="cache-service",
        timestamp="2026-10-28T12:00:00Z",
        summary="eviction_rate_per_sec spiked to 5000",
        anomaly_score=0.88,
    )
    e_log = NormalizedEvidence(
        id="EVID-L1",
        incident_id="INC-TEST-4",
        evidence_type=EvidenceType.LOG,
        service="cache-service",
        timestamp="2026-10-28T12:00:45Z",
        summary="OOMKilled: Redis memory limit exceeded",
        severity=EvidenceSeverity.CRITICAL,
        anomaly_score=0.90,
    )

    correlations = correlation_engine.find_all_correlations([e_metric, e_log])

    assert len(correlations) > 0
    rel_types = [c.relation_type for c in correlations]
    assert "METRIC_ANOMALY_PROXIMITY" in rel_types or "SAME_SERVICE" in rel_types
    # Check that explanation reason is descriptive
    assert any("cache-service" in c.reason for c in correlations)


# =============================================================================
# TEST 5: No meaningful evidence exists -> Returns UNKNOWN / INSUFFICIENT EVIDENCE
# =============================================================================
def test_5_no_meaningful_evidence_returns_insufficient_evidence(clean_storage):
    svc = ServiceNode(id="worker-service", name="Worker")
    clean_storage.save_service(svc)

    incident = Incident(
        id="INC-TEST-5",
        title="Uncorrelated quiet incident",
        affected_services=["worker-service"],
        started_at="2026-10-28T08:00:00Z",
    )
    clean_storage.save_incident(incident)

    # Telemetry is entirely normal / non-anomalous
    e_normal = NormalizedEvidence(
        id="EVID-NORM-1",
        incident_id="INC-TEST-5",
        evidence_type=EvidenceType.LOG,
        service="worker-service",
        timestamp="2026-10-28T08:02:00Z",
        summary="Processed queue task 42 successfully",
        severity=EvidenceSeverity.INFO,
        anomaly_score=0.01,
    )
    clean_storage.save_evidence_batch([e_normal])

    engine = RCAEngine(clean_storage)
    result = engine.run_rca("INC-TEST-5", trigger_llm=False)

    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.is_insufficient_evidence is True
    assert "UNKNOWN / INSUFFICIENT EVIDENCE" in result.reason


# =============================================================================
# TEST 6: Conflicting evidence exists -> Does not pretend certainty
# =============================================================================
def test_6_conflicting_evidence_does_not_pretend_certainty(clean_storage):
    # Two independent services with no dependency link between them
    s1 = ServiceNode(id="cluster-east", name="East")
    s2 = ServiceNode(id="cluster-west", name="West")
    clean_storage.save_service(s1)
    clean_storage.save_service(s2)

    incident = Incident(
        id="INC-TEST-6",
        title="Ambiguous multi-datacenter blip",
        affected_services=["cluster-east", "cluster-west"],
        started_at="2026-10-28T07:00:00Z",
    )
    clean_storage.save_incident(incident)

    evidence = [
        # Exactly identical error signals at the exact same second
        NormalizedEvidence(
            id="EVID-EAST",
            incident_id="INC-TEST-6",
            evidence_type=EvidenceType.LOG,
            service="cluster-east",
            timestamp="2026-10-28T07:01:00Z",
            summary="Transient network reset",
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.80,
        ),
        NormalizedEvidence(
            id="EVID-WEST",
            incident_id="INC-TEST-6",
            evidence_type=EvidenceType.LOG,
            service="cluster-west",
            timestamp="2026-10-28T07:01:00Z",
            summary="Transient network reset",
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.80,
        ),
    ]
    clean_storage.save_evidence_batch(evidence)

    engine = RCAEngine(clean_storage)
    result = engine.run_rca("INC-TEST-6", trigger_llm=False)

    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert "Conflicting telemetry evidence detected" in result.reason


# =============================================================================
# TEST 7: Invalid evidence ID supplied -> Validator rejects it
# =============================================================================
def test_7_invalid_evidence_id_rejected_by_validator():
    real_ids = {"EVID-REAL-001", "EVID-REAL-002"}

    hypothesis_packet = {
        "incident_summary": "Incident caused by phantom error EVID-HALLUCINATED-999.",
        "most_likely_cause": "Ghost fault",
        "supporting_evidence": ["EVID-REAL-001", "EVID-HALLUCINATED-999"],
        "confidence_explanation": "Deterministic score 0.90",
    }

    is_valid, invalid_ids, sanitized = EvidenceValidator.validate_llm_hypothesis(
        hypothesis_packet, real_ids
    )

    assert is_valid is False
    assert "EVID-HALLUCINATED-999" in invalid_ids
    assert sanitized["validation_passed"] is False
    # Verified references retain real IDs only
    assert sanitized["verified_evidence_refs"] == ["EVID-REAL-001"]
    assert "EVID-HALLUCINATED-999" not in sanitized["supporting_evidence"]


# =============================================================================
# TEST 8: Duplicate evidence records exist -> Handled safely
# =============================================================================
def test_8_duplicate_evidence_handled_safely(clean_storage):
    svc = ServiceNode(id="dedup-service", name="Dedup Service")
    clean_storage.save_service(svc)

    incident = Incident(
        id="INC-TEST-8",
        title="Deduplication test incident",
        affected_services=["dedup-service"],
        started_at="2026-10-28T13:00:00Z",
    )
    clean_storage.save_incident(incident)

    ev1 = NormalizedEvidence(
        id="EVID-DUP-01",
        incident_id="INC-TEST-8",
        evidence_type=EvidenceType.LOG,
        service="dedup-service",
        timestamp="2026-10-28T13:01:00Z",
        summary="Disk space low warning",
        severity=EvidenceSeverity.HIGH,
        anomaly_score=0.85,
    )
    # Identical record re-saved
    ev1_duplicate = NormalizedEvidence(
        id="EVID-DUP-01",
        incident_id="INC-TEST-8",
        evidence_type=EvidenceType.LOG,
        service="dedup-service",
        timestamp="2026-10-28T13:01:00Z",
        summary="Disk space low warning",
        severity=EvidenceSeverity.HIGH,
        anomaly_score=0.85,
    )

    clean_storage.save_evidence(ev1)
    clean_storage.save_evidence(ev1_duplicate)  # Should upsert safely without IntegrityError

    fetched = clean_storage.get_evidence_by_incident("INC-TEST-8")
    assert len(fetched) == 1

    engine = RCAEngine(clean_storage)
    result = engine.run_rca("INC-TEST-8", trigger_llm=False)
    assert result.status == "SUCCESS"


# =============================================================================
# TEST 9: Malformed input record exists -> Ingestion reports error without crashing batch
# =============================================================================
def test_9_malformed_input_reported_without_crashing_batch():
    ingestor = GenericTelemetryIngestor()

    raw_batch = [
        # Record 0: Valid
        {
            "service": "order-service",
            "timestamp": "2026-10-28T15:00:00Z",
            "level": "INFO",
            "message": "Order 1001 created",
        },
        # Record 1: Malformed (missing mandatory fields or invalid structure)
        "this is a corrupt string inside a records list",
        # Record 2: Valid
        {
            "service": "order-service",
            "timestamp": "2026-10-28T15:01:00Z",
            "level": "ERROR",
            "message": "Payment processing failed",
        },
    ]

    normalized, report = ingestor.parse(raw_batch, incident_id="INC-TEST-9")

    # The valid 2 records must be ingested
    assert len(normalized) == 2
    # The malformed record must be captured in the errors report
    assert report["ingested_count"] == 2
    assert report["failed_count"] >= 1 or len(report["warnings"]) >= 1
    assert report["status"] == "PARTIAL_SUCCESS"
