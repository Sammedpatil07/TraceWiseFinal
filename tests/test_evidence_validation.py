"""Unit tests for Evidence Validation and LLM Citation Integrity.
"""

from app.models.incident import CandidateCause
from app.engine.validator import EvidenceValidator


def test_candidate_evidence_validation():
    valid_ids = {"ev_1", "ev_2", "ev_3"}

    candidate = CandidateCause(
        id="c1",
        incident_id="inc1",
        service_id="payment-service",
        title="Pool exhaustion",
        description="Pool exhausted",
        candidate_type="RESOURCE_EXHAUSTION",
        supporting_evidence_ids=["ev_1", "ev_fake_hallucinated", "ev_2"],
        contradicting_evidence_ids=["ev_3", "ev_ghost"],
    )

    validated = EvidenceValidator.validate_candidate_evidence(candidate, valid_ids)

    # Fake IDs must be stripped
    assert validated.supporting_evidence_ids == ["ev_1", "ev_2"]
    assert validated.contradicting_evidence_ids == ["ev_3"]


def test_llm_hypothesis_evidence_validation():
    valid_ids = {"EVID-DEMO-001", "EVID-DEMO-002", "log_abc123"}

    # Case 1: Valid LLM response referencing only real IDs
    valid_hypothesis = {
        "incident_summary": "Incident triggered by configuration EVID-DEMO-001.",
        "most_likely_cause": "Config error on payment service",
        "supporting_evidence": ["EVID-DEMO-001", "EVID-DEMO-002"],
        "timeline_interpretation": "Followed by log_abc123.",
    }
    is_valid, invalid_ids, sanitized = EvidenceValidator.validate_llm_hypothesis(valid_hypothesis, valid_ids)
    assert is_valid is True
    assert len(invalid_ids) == 0
    assert sanitized["validation_passed"] is True
    assert sanitized["verified_evidence_refs"] == ["EVID-DEMO-001", "EVID-DEMO-002"]

    # Case 2: Hallucinated / Fake ID in LLM response
    hallucinated_hypothesis = {
        "incident_summary": "Incident caused by phantom error EVID-FAKE-999.",
        "most_likely_cause": "Unknown failure",
        "supporting_evidence": ["EVID-DEMO-001", "EVID-HALLUCINATED-007"],
        "timeline_interpretation": "Cascaded to gateway.",
    }
    is_valid, invalid_ids, sanitized = EvidenceValidator.validate_llm_hypothesis(hallucinated_hypothesis, valid_ids)
    assert is_valid is False
    assert "EVID-HALLUCINATED-007" in invalid_ids or "EVID-FAKE-999" in invalid_ids
    assert sanitized["validation_passed"] is False
    assert "EVID-DEMO-001" in sanitized["verified_evidence_refs"]
