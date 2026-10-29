"""Unit tests for Timeline Generation from normalized evidence.
"""

from app.models.evidence import NormalizedEvidence, EvidenceType, EvidenceSeverity
from app.engine.timeline import generate_incident_timeline


def test_timeline_chronological_ordering_and_evidence_linking():
    ev_early = NormalizedEvidence(
        id="ev_01",
        incident_id="inc_1",
        evidence_type=EvidenceType.CONFIGURATION,
        service_id="payment-service",
        timestamp="2026-10-28T10:00:00Z",
        summary="Pool config lowered to 5",
        severity=EvidenceSeverity.HIGH,
    )
    ev_mid = NormalizedEvidence(
        id="ev_02",
        incident_id="inc_1",
        evidence_type=EvidenceType.METRIC,
        service_id="payment-service",
        timestamp="2026-10-28T10:05:00Z",
        summary="Latency spiked to 4000ms",
        severity=EvidenceSeverity.CRITICAL,
        anomaly_score=0.9,
    )
    ev_late = NormalizedEvidence(
        id="ev_03",
        incident_id="inc_1",
        evidence_type=EvidenceType.LOG,
        service_id="payment-service",
        timestamp="2026-10-28T10:30:00Z",
        summary="Restarted and recovered",
        severity=EvidenceSeverity.INFO,
    )

    # Provide in reverse order to test sorting
    timeline = generate_incident_timeline([ev_late, ev_early, ev_mid])

    assert len(timeline) == 3
    # Check chronological ordering
    assert timeline[0].evidence_id == "ev_01"
    assert timeline[1].evidence_id == "ev_02"
    assert timeline[2].evidence_id == "ev_03"

    # Check event types
    assert timeline[0].event_type == "TRIGGER"  # Earliest high impact change is tagged trigger
    assert timeline[1].event_type == "METRIC_SPIKE"
    assert timeline[2].event_type == "RECOVERY"

    # Check evidence ID retention
    for t in timeline:
        assert t.evidence_id in ["ev_01", "ev_02", "ev_03"]
