"""Unit tests for Insufficient Evidence guardrail.
Verifies requirement:
"If evidence is insufficient, the system must return UNKNOWN / INSUFFICIENT EVIDENCE."
"""

import pytest
import os
from app.storage.sqlite_adapter import SqliteStorage
from app.models.incident import Incident
from app.models.evidence import (
    NormalizedEvidence,
    EvidenceType,
    EvidenceSeverity,
    ServiceNode,
)
from app.engine.rca_engine import RCAEngine


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test_ao03.db")
    storage = SqliteStorage(db_file)
    storage.save_service(ServiceNode(id="svc-a", name="Service A"))
    return storage


def test_empty_evidence_returns_insufficient_evidence(test_db):
    incident = Incident(
        id="INC-EMPTY",
        title="Empty incident without telemetry",
        description="No logs or metrics attached",
        affected_services=["svc-a"],
    )
    test_db.save_incident(incident)

    engine = RCAEngine(test_db)
    result = engine.run_rca("INC-EMPTY", trigger_llm=False)

    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert "UNKNOWN / INSUFFICIENT EVIDENCE" in result.reason


def test_sparse_uncorrelated_evidence_returns_insufficient_evidence(test_db):
    incident = Incident(
        id="INC-SPARSE",
        title="Sparse Informational Incident",
        description="Routine background info only",
        affected_services=["svc-a"],
    )
    test_db.save_incident(incident)

    # Only normal, non-anomalous telemetry
    ev = NormalizedEvidence(
        id="ev_sparse_1",
        incident_id="INC-SPARSE",
        evidence_type=EvidenceType.LOG,
        service_id="svc-a",
        timestamp="2026-10-28T12:00:00Z",
        summary="Routine ping normal",
        severity=EvidenceSeverity.INFO,
        anomaly_score=0.01,
    )
    test_db.save_evidence(ev)

    engine = RCAEngine(test_db)
    result = engine.run_rca("INC-SPARSE", trigger_llm=False)

    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert "UNKNOWN / INSUFFICIENT EVIDENCE" in result.reason
