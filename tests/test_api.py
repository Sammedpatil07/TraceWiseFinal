"""Integration tests for Flask API routes.
"""

import pytest
import json
from app import create_app
from app.storage import reset_storage
from app.config import Config


@pytest.fixture
def client(tmp_path):
    reset_storage()
    Config.DATABASE_BACKEND = "sqlite"
    Config.STORAGE_BACKEND = "sqlite"
    Config.SQLITE_DB_PATH = str(tmp_path / "test_api.db")
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-api-secret"
    with app.test_client() as client:
        # Authenticate as admin for full integration test permissions
        client.post("/api/auth/login", json={"username": "admin", "password": "Admin!Pass2026"})
        yield client
    reset_storage()


def test_api_stats_and_demo_loading(client):
    # Initial empty stats
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_incidents"] == 0

    # Load synthetic demo fixtures
    res = client.post("/api/demo/load")
    assert res.status_code == 200
    demo_res = res.get_json()
    assert demo_res["status"] == "SUCCESS"
    assert demo_res["counts"]["incidents"] >= 2
    assert demo_res["counts"]["evidence"] >= 10

    # Stats now reflect data
    res = client.get("/api/stats")
    data = res.get_json()
    assert data["total_incidents"] >= 2
    assert data["evidence_count"] >= 10


def test_api_rca_execution(client):
    # Load demo data
    client.post("/api/demo/load")

    # Run RCA on INC-2026-001 (has full causal chain)
    res = client.post("/api/incidents/INC-2026-001/rca", json={"trigger_llm": False})
    assert res.status_code == 200
    rca = res.get_json()

    assert rca["status"] == "SUCCESS"
    assert rca["top_candidate"] is not None
    assert rca["top_candidate"]["service_id"] == "payment-service"
    assert len(rca["timeline"]) > 0
    assert len(rca["top_candidate"]["supporting_evidence_ids"]) > 0

    # Test RCA on INC-2026-002 (sparse telemetry -> INSUFFICIENT_EVIDENCE)
    res = client.post("/api/incidents/INC-2026-002/rca", json={"trigger_llm": False})
    assert res.status_code == 200
    sparse_rca = res.get_json()
    assert sparse_rca["status"] == "INSUFFICIENT_EVIDENCE"
    assert "UNKNOWN / INSUFFICIENT EVIDENCE" in sparse_rca["reason"]


def test_generic_ingest_endpoint(client):
    payload = {
        "incident_id": "INC-NEW-001",
        "evidence_type": "LOG",
        "records": [
            {
                "service": "billing-service",
                "time": "2026-10-28T16:00:00Z",
                "level": "ERROR",
                "message": "Payment token invalid",
            }
        ]
    }
    res = client.post("/api/ingest", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["ingested_count"] == 1

    # Verify queryable via evidence API
    ev_res = client.get("/api/evidence?incident_id=INC-NEW-001")
    assert ev_res.status_code == 200
    ev_list = ev_res.get_json()
    assert len(ev_list) == 1
    assert ev_list[0]["service_id"] == "billing-service"
