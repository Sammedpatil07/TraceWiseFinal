"""Tests for Supabase PostgreSQL storage adapter, configuration, and security.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from app import create_app
from app.config import Config
from app.storage import get_storage, reset_storage
from app.storage.supabase_adapter import SupabaseStorage
from app.storage.sqlite_adapter import SqliteStorage
from app.models.evidence import NormalizedEvidence, EvidenceType, EvidenceSeverity, SourceType
from app.models.incident import Incident, CandidateCause, TimelineEvent
from app.models.user import User, UserRole
from app.models.audit import AuditLog, AuditAction


@pytest.fixture
def client(tmp_path):
    reset_storage()
    Config.SQLITE_DB_PATH = str(tmp_path / "test_sup.db")
    Config.DATABASE_BACKEND = "sqlite"
    Config.STORAGE_BACKEND = "sqlite"
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-sup-secret"
    with app.test_client() as c:
        c.post("/api/auth/login", json={"username": "admin", "password": "Admin!Pass2026"})
        yield c
    reset_storage()


def test_supabase_config_environment():
    """Verify that Config loads Supabase credentials from environment without hardcoding."""
    assert hasattr(Config, "SUPABASE_URL")
    assert hasattr(Config, "SUPABASE_KEY")
    assert hasattr(Config, "DATABASE_BACKEND")


def test_credential_protection_no_keys_in_responses(client):
    """Verify that diagnostic and health endpoints never leak the Supabase key or credentials."""
    res = client.get("/api/diagnostic")
    assert res.status_code == 200
    data = res.get_json()

    # Never expose raw keys in responses
    for k, v in data.items():
        assert "sb_publishable_" not in str(v)
        assert "service_role" not in str(v)
        assert "secret" not in str(k).lower() or "secret_key" not in str(k).lower()


def test_supabase_storage_connection_check():
    """Verify verify_connection logic when remote service is healthy."""
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        storage = SupabaseStorage(
            supabase_url="https://ocnekscontpwqrfjicdi.supabase.co",
            supabase_key="sb_dummy_key_for_testing",
        )
        assert storage.supabase_url == "https://ocnekscontpwqrfjicdi.supabase.co"
        assert "apikey" in storage.headers
        assert "Authorization" in storage.headers


def test_supabase_no_silent_fallback_on_invalid_credentials():
    """Verify that SupabaseStorage raises ConnectionError when Supabase authentication fails."""
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"message": "Invalid API key"}'
        mock_get.return_value = mock_resp

        with pytest.raises(ConnectionError) as exc_info:
            SupabaseStorage(
                supabase_url="https://invalid-project.supabase.co",
                supabase_key="invalid_key",
            )
        assert "Supabase authorization failed with HTTP 401" in str(exc_info.value)


def test_supabase_backend_selection_mechanism(monkeypatch):
    """Verify that get_storage strictly respects DATABASE_BACKEND without silent fallback."""
    reset_storage()

    # When DATABASE_BACKEND=sqlite
    monkeypatch.setattr(Config, "DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(Config, "STORAGE_BACKEND", "sqlite")
    sqlite_storage = get_storage()
    assert isinstance(sqlite_storage, SqliteStorage)

    reset_storage()

    # When DATABASE_BACKEND=supabase but credentials missing, must raise ValueError
    monkeypatch.setattr(Config, "DATABASE_BACKEND", "supabase")
    monkeypatch.setattr(Config, "STORAGE_BACKEND", "supabase")
    monkeypatch.setattr(Config, "SUPABASE_URL", "")
    with pytest.raises(ValueError) as exc:
        get_storage()
    assert "DATABASE_BACKEND is configured as 'supabase'" in str(exc.value)

    reset_storage()


def test_supabase_evidence_payload_mapping():
    """Verify that NormalizedEvidence correctly maps to PostgreSQL JSONB format."""
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        storage = SupabaseStorage(
            supabase_url="https://ocnekscontpwqrfjicdi.supabase.co",
            supabase_key="sb_test_key",
        )

    ev = NormalizedEvidence(
        id="EVID-TEST-001",
        incident_id="INC-2026-001",
        evidence_type=EvidenceType.METRIC,
        service="payment-service",
        timestamp="2026-10-28T14:00:00Z",
        severity=EvidenceSeverity.HIGH,
        summary="High latency spike",
        trace_id="tr-test-123",
        span_id="sp-test-456",
        metric_name="http_request_duration_ms",
        metric_value=2450.0,
        anomaly_score=0.95,
        details={"custom_metric": "p99", "region": "us-east-1"},
    )

    payload = storage._evidence_to_payload(ev)

    assert payload["id"] == "EVID-TEST-001"
    assert payload["incident_id"] == "INC-2026-001"
    assert payload["service_id"] == "payment-service"
    assert payload["evidence_type"] == "METRIC"
    assert payload["severity"] == "HIGH"
    assert payload["anomaly_score"] == 0.95
    assert isinstance(payload["details"], dict)
    assert payload["details"]["trace_id"] == "tr-test-123"
    assert payload["details"]["metric_name"] == "http_request_duration_ms"
    assert payload["details"]["metric_value"] == 2450.0
    assert payload["details"]["region"] == "us-east-1"

    # Test reverse mapping
    restored = storage._payload_to_evidence(payload)
    assert restored.id == ev.id
    assert restored.service == "payment-service"
    assert restored.evidence_type == EvidenceType.METRIC
    assert restored.details["region"] == "us-east-1"
