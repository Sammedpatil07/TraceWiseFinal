"""Unit tests for Deterministic RCA Evidence Correlation and Scoring.
"""

from app.models.evidence import (
    NormalizedEvidence,
    EvidenceType,
    EvidenceSeverity,
    ServiceNode,
    ServiceDependency,
)
from app.models.incident import Incident
from app.engine.dependency_graph import DependencyGraphManager
from app.engine.correlation import CorrelationEngine


def test_deterministic_scoring_and_ranking():
    services = [
        ServiceNode(id="api-gateway", name="Gateway"),
        ServiceNode(id="order-service", name="Orders"),
        ServiceNode(id="payment-service", name="Payments"),
    ]
    dependencies = [
        ServiceDependency(id="d1", source_service="api-gateway", target_service="order-service"),
        ServiceDependency(id="d2", source_service="order-service", target_service="payment-service"),
    ]
    graph = DependencyGraphManager(services, dependencies)
    engine = CorrelationEngine(graph)

    incident = Incident(
        id="inc_test",
        title="Gateway timeout incident",
        description="Checkout broken",
        affected_services=["api-gateway", "order-service", "payment-service"],
    )

    evidence = [
        # payment-service has early config change & metric anomaly
        NormalizedEvidence(
            id="e1",
            incident_id="inc_test",
            evidence_type=EvidenceType.CONFIGURATION,
            service_id="payment-service",
            timestamp="2026-10-28T14:00:00Z",
            summary="Config changed pool size to 2",
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.9,
        ),
        NormalizedEvidence(
            id="e2",
            incident_id="inc_test",
            evidence_type=EvidenceType.METRIC,
            service_id="payment-service",
            timestamp="2026-10-28T14:02:00Z",
            summary="Latency high",
            severity=EvidenceSeverity.CRITICAL,
            anomaly_score=0.95,
        ),
        # api-gateway only has downstream 504 error later
        NormalizedEvidence(
            id="e3",
            incident_id="inc_test",
            evidence_type=EvidenceType.LOG,
            service_id="api-gateway",
            timestamp="2026-10-28T14:08:00Z",
            summary="504 Gateway Timeout",
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.7,
        ),
    ]

    candidates = engine.evaluate_candidates(incident, evidence)

    assert len(candidates) == 2
    # Top candidate should be payment-service due to temporal precedence, change proximity, and anomaly magnitude
    top = candidates[0]
    assert top.service_id == "payment-service"
    assert top.rank == 1
    assert 0.0 <= top.confidence_score <= 1.0

    # api-gateway should rank lower as an upstream symptom
    second = candidates[1]
    assert second.service_id == "api-gateway"
    assert second.rank == 2
    assert second.confidence_score < top.confidence_score

    # Scoring breakdown attributes exist
    breakdown = top.scoring_breakdown
    assert "temporal_precedence" in breakdown
    assert "anomaly_magnitude" in breakdown
    assert "change_proximity" in breakdown
    assert "blast_reachability" in breakdown
