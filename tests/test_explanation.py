"""Regression tests for the ExplanationService (AO-03).

These tests mock the Ollama provider so no running Ollama instance is required.
They cover the real incident RCA explanation workflow path, including the
markdown-code-fence regression that caused `Expecting value: line 1 column 1 (char 0)`.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.llm.explanation import ExplanationService


def _make_incident():
    from app.models.incident import Incident
    return Incident(
        id="INC-2026-001",
        title="Checkout & Payment Gateway 504 Timeout Cascade",
        description="504 errors on api-gateway after a deployment to payment-service.",
        started_at="2026-10-28T14:00:00+00:00",
        resolved_at="2026-10-28T14:30:00+00:00",
        affected_services=["api-gateway", "order-service", "payment-service"],
    )


def _make_candidate(service_id="payment-service", title="Configuration drift on payment-service"):
    from app.models.incident import CandidateCause
    return CandidateCause(
        id="cand_1",
        incident_id="INC-2026-001",
        service_id=service_id,
        title=title,
        candidate_type="CONFIG_DRIFT",
        rank=1,
        evidence_score=0.99,
        supporting_evidence_ids=["EVID-DEMO-001"],
        contradicting_evidence_ids=[],
    )


def _make_timeline():
    from app.models.incident import TimelineEvent
    return [
        TimelineEvent(
            id="tl_1", incident_id="INC-2026-001", timestamp="2026-10-28T14:00:00+00:00",
            event_type="CONFIG_CHANGE", service_id="payment-service",
            summary="Deployment v2.4.1 applied config change", evidence_id="EVID-DEMO-002",
        )
    ]


def _make_evidence():
    from app.models.evidence import NormalizedEvidence, EvidenceType
    return [
        NormalizedEvidence(
            id="EVID-DEMO-001", incident_id="INC-2026-001",
            source_type="ORGANIZER", timestamp="2026-10-28T14:00:00+00:00",
            service_id="payment-service", severity="HIGH", event_type="CONFIG_CHANGE",
            summary="db.pool.max_connections changed from 50 to 5", evidence_id="EVID-DEMO-001",
        )
    ]


def _mock_provider(generate_return, available=True):
    provider = MagicMock()
    provider.is_available.return_value = available
    provider.generate.return_value = generate_return
    return provider


class TestExplanationServiceValidResponse:
    def test_valid_ollama_response_is_used(self):
        hypothesis = {
            "header": "AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING",
            "incident_summary": "504 cascade",
            "most_likely_cause": "Configuration drift on payment-service",
            "confidence_explanation": "score is high",
            "supporting_evidence": ["EVID-DEMO-001"],
            "contradicting_evidence": [],
            "alternative_causes": [],
            "timeline_interpretation": "cascade",
            "unknowns": "none",
            "hypothesis_status": "GENERATED",
        }
        svc = ExplanationService()
        svc.ollama = _mock_provider(json.dumps(hypothesis))
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "AVAILABLE"
        assert parsed["hypothesis_status"] == "AI_GENERATED"
        assert parsed["most_likely_cause"] == "Configuration drift on payment-service"
        assert "EVID-DEMO-001" in parsed["supporting_evidence"]

    def test_heuristic_is_not_marked_as_ollama(self):
        svc = ExplanationService()
        svc.ollama = _mock_provider(None, available=True)
        svc.ollama.generate.side_effect = RuntimeError("boom")
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "FALLBACK_HEURISTIC"
        assert parsed["hypothesis_status"] == "DETERMINISTIC_HEURISTIC"


class TestExplanationServiceFencedMarkdown:
    """Regression: Ollama instruction models wrap JSON in markdown code fences."""

    def test_fenced_json_marked_json(self):
        payload = (
            "```json\n"
            '{"most_likely_cause": "Configuration drift on payment-service", '
            '"incident_summary": "504 cascade", "supporting_evidence": ["EVID-DEMO-001"], '
            '"contradicting_evidence": [], "alternative_causes": [], '
            '"timeline_interpretation": "cascade", "unknowns": "none", '
            '"confidence_explanation": "high", "header": "AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING", '
            '"hypothesis_status": "GENERATED"}\n'
            "```"
        )
        svc = ExplanationService()
        svc.ollama = _mock_provider(payload)
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "AVAILABLE"
        assert parsed["most_likely_cause"] == "Configuration drift on payment-service"
        assert parsed["hypothesis_status"] == "AI_GENERATED"

    def test_fenced_json_without_language_tag(self):
        payload = "```\n{\"most_likely_cause\": \"Configuration drift\"}\n```"
        svc = ExplanationService()
        svc.ollama = _mock_provider(payload)
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "AVAILABLE"
        assert parsed["most_likely_cause"] == "Configuration drift"


class TestExplanationServiceFailureFallback:
    def test_empty_response_falls_back(self):
        svc = ExplanationService()
        svc.ollama = _mock_provider("")
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "FALLBACK_HEURISTIC"
        assert parsed["hypothesis_status"] == "DETERMINISTIC_HEURISTIC"

    def test_none_response_falls_back(self):
        svc = ExplanationService()
        svc.ollama = _mock_provider(None)
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "FALLBACK_HEURISTIC"
        assert parsed["hypothesis_status"] == "DETERMINISTIC_HEURISTIC"

    def test_malformed_json_falls_back(self):
        svc = ExplanationService()
        svc.ollama = _mock_provider("not json at all {{{")
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "FALLBACK_HEURISTIC"

    def test_non_dict_json_falls_back(self):
        svc = ExplanationService()
        svc.ollama = _mock_provider("[1, 2, 3]")
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "FALLBACK_HEURISTIC"

    def test_ollama_unavailable_falls_back(self):
        svc = ExplanationService()
        svc.ollama = _mock_provider("{}", available=False)
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "FALLBACK_HEURISTIC"

    def test_prose_without_json_falls_back(self):
        """Ollama sometimes returns prose instead of JSON; must fall back clearly."""
        svc = ExplanationService()
        svc.ollama = _mock_provider("I cannot determine the root cause from this telemetry.")
        parsed, status = svc.generate_explanation(
            _make_incident(), _make_candidate(), [_make_candidate()], _make_timeline(), _make_evidence()
        )
        assert status == "FALLBACK_HEURISTIC"
        assert parsed["hypothesis_status"] == "DETERMINISTIC_HEURISTIC"

