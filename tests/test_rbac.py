"""Automated tests for Role-Based Access Control (RBAC) and Authentication.
"""

import pytest
import json
from app import create_app
from app.storage import reset_storage, get_storage
from app.config import Config
from app.models.user import UserRole
from app.ingestion.demo_fixtures import load_demo_data


@pytest.fixture
def rbac_client(tmp_path):
    reset_storage()
    Config.DATABASE_BACKEND = "sqlite"
    Config.STORAGE_BACKEND = "sqlite"
    Config.SQLITE_DB_PATH = str(tmp_path / "test_rbac.db")
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-rbac"

    with app.test_client() as client:
        # Load demo fixtures into test database using direct storage
        storage = get_storage()
        load_demo_data(storage)
        yield client

    reset_storage()


def login_as(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# 1. Unauthenticated user cannot access protected routes
def test_unauthenticated_user_blocked(rbac_client):
    protected_endpoints = [
        ("GET", "/api/stats"),
        ("GET", "/api/incidents"),
        ("GET", "/api/services"),
        ("GET", "/api/evaluation"),
        ("GET", "/api/admin/users"),
        ("POST", "/api/incidents/INC-2026-001/rca"),
        ("POST", "/api/ingest"),
        ("POST", "/api/demo/load"),
    ]
    for method, endpoint in protected_endpoints:
        if method == "GET":
            res = rbac_client.get(endpoint)
        else:
            res = rbac_client.post(endpoint, json={})
        assert res.status_code == 401, f"Expected 401 for unauthenticated {method} {endpoint}, got {res.status_code}"
        data = res.get_json()
        assert data.get("code") == "UNAUTHORIZED"


# 2. Admin can log in and access admin routes
def test_admin_access(rbac_client):
    login_res = login_as(rbac_client, "admin", "Admin!Pass2026")
    assert login_res.status_code == 200
    user_data = login_res.get_json()["user"]
    assert user_data["role"] == UserRole.ADMIN

    # Admin accesses users list
    res = rbac_client.get("/api/admin/users")
    assert res.status_code == 200
    users = res.get_json()
    assert len(users) >= 3
    # Verify passwords are never exposed in user list
    for u in users:
        assert "password" not in u
        assert "password_hash" not in u

    # Admin accesses audit logs
    audit_res = rbac_client.get("/api/admin/audit-logs")
    assert audit_res.status_code == 200
    logs = audit_res.get_json()
    assert len(logs) > 0


# 3. Admin can create new user and update role/status
def test_admin_user_management(rbac_client):
    login_as(rbac_client, "admin", "Admin!Pass2026")

    # Create new user
    create_res = rbac_client.post("/api/admin/users", json={
        "username": "new_sre",
        "password": "SecurePassword123!",
        "role": "INCIDENT_RESPONDER",
        "email": "newsre@tracewise.internal",
    })
    assert create_res.status_code == 201
    created_user = create_res.get_json()["user"]
    user_id = created_user["id"]
    assert created_user["username"] == "new_sre"
    assert created_user["role"] == UserRole.INCIDENT_RESPONDER

    # Update role to VIEWER
    update_role_res = rbac_client.put(f"/api/admin/users/{user_id}/role", json={"role": "VIEWER"})
    assert update_role_res.status_code == 200
    assert update_role_res.get_json()["user"]["role"] == UserRole.VIEWER

    # Toggle user status (disable)
    status_res = rbac_client.put(f"/api/admin/users/{user_id}/status", json={"is_active": False})
    assert status_res.status_code == 200
    assert status_res.get_json()["user"]["is_active"] is False


# 4. Incident Responder can investigate incidents
def test_incident_responder_investigation(rbac_client):
    login_as(rbac_client, "sre_responder", "Sre!Pass2026")

    # Can access dashboard and stats
    assert rbac_client.get("/api/stats").status_code == 200
    assert rbac_client.get("/api/incidents").status_code == 200

    # Can execute RCA
    rca_res = rbac_client.post("/api/incidents/INC-2026-001/rca", json={"trigger_llm": False})
    assert rca_res.status_code == 200
    data = rca_res.get_json()
    assert data["status"] == "SUCCESS"
    assert data["top_candidate"]["service_id"] == "payment-service"

    # Can inspect deep raw evidence
    evidence_res = rbac_client.get("/api/evidence/EVID-DEMO-001")
    assert evidence_res.status_code == 200


# 5. Incident Responder cannot access user management or ingestion
def test_incident_responder_restrictions(rbac_client):
    login_as(rbac_client, "sre_responder", "Sre!Pass2026")

    # Cannot list users
    assert rbac_client.get("/api/admin/users").status_code == 403

    # Cannot create users
    assert rbac_client.post("/api/admin/users", json={"username": "hacker", "password": "password"}).status_code == 403

    # Cannot ingest telemetry
    assert rbac_client.post("/api/ingest", json={"incident_id": "INC-01"}).status_code == 403

    # Cannot load/reset demo data
    assert rbac_client.post("/api/demo/load").status_code == 403
    assert rbac_client.post("/api/demo/reset").status_code == 403


# 6. Viewer can access permitted read-only pages
def test_viewer_read_only_access(rbac_client):
    login_as(rbac_client, "auditor_viewer", "Viewer!Pass2026")

    assert rbac_client.get("/api/stats").status_code == 200
    assert rbac_client.get("/api/incidents").status_code == 200
    assert rbac_client.get("/api/incidents/INC-2026-001").status_code == 200
    assert rbac_client.get("/api/incidents/INC-2026-001/rca").status_code == 200
    assert rbac_client.get("/api/incidents/INC-2026-001/timeline").status_code == 200
    assert rbac_client.get("/api/incidents/INC-2026-001/graph").status_code == 200
    assert rbac_client.get("/api/evaluation").status_code == 200


# 7. Viewer cannot bypass frontend restrictions by calling protected APIs
def test_viewer_bypass_prevention(rbac_client):
    login_as(rbac_client, "auditor_viewer", "Viewer!Pass2026")

    # Viewer CANNOT trigger new RCA
    rca_res = rbac_client.post("/api/incidents/INC-2026-001/rca", json={"trigger_llm": False})
    assert rca_res.status_code == 403
    assert rca_res.get_json()["code"] == "FORBIDDEN"

    # Viewer CANNOT perform deep raw evidence lookup
    deep_ev_res = rbac_client.get("/api/evidence/EVID-DEMO-001")
    assert deep_ev_res.status_code == 403
    assert deep_ev_res.get_json()["code"] == "FORBIDDEN"

    # Viewer CANNOT access admin users
    assert rbac_client.get("/api/admin/users").status_code == 403

    # Viewer CANNOT access audit logs
    assert rbac_client.get("/api/admin/audit-logs").status_code == 403

    # Viewer CANNOT ingest telemetry
    assert rbac_client.post("/api/ingest", json={"incident_id": "INC-01"}).status_code == 403


# 8. Viewer receives sanitized/redacted evidence list
def test_viewer_telemetry_redaction(rbac_client):
    login_as(rbac_client, "auditor_viewer", "Viewer!Pass2026")

    ev_list_res = rbac_client.get("/api/evidence")
    assert ev_list_res.status_code == 200
    items = ev_list_res.get_json()
    assert len(items) > 0
    for item in items:
        # Details dictionary must be sanitized and marked restricted
        assert item["details"].get("restricted") is True
        assert item["source_record"] is None


# 9. Logout invalidates session
def test_logout_invalidates_session(rbac_client):
    login_as(rbac_client, "admin", "Admin!Pass2026")
    assert rbac_client.get("/api/stats").status_code == 200

    # Logout
    logout_res = rbac_client.post("/api/auth/logout")
    assert logout_res.status_code == 200

    # Subsequent request is blocked with 401
    assert rbac_client.get("/api/stats").status_code == 401
    assert rbac_client.get("/api/admin/users").status_code == 401


# 10. Passwords are never stored plaintext in database
def test_passwords_never_plaintext(rbac_client):
    storage = get_storage()
    users = storage.get_all_users()
    for u in users:
        # Check password hash is not the plaintext password
        assert u.password_hash != "Admin!Pass2026"
        assert u.password_hash != "Sre!Pass2026"
        assert u.password_hash != "Viewer!Pass2026"
        assert u.password_hash.startswith("scrypt:") or u.password_hash.startswith("pbkdf2:")


# 11. Security Audit Logs record actions and denials
def test_audit_logging_mechanism(rbac_client):
    # Try invalid login
    bad_login = login_as(rbac_client, "admin", "WrongPassword!")
    assert bad_login.status_code == 401

    # Unauthorized access attempt as viewer
    login_as(rbac_client, "auditor_viewer", "Viewer!Pass2026")
    rbac_client.get("/api/admin/users")

    # Log in as admin and verify audit logs recorded both events
    login_as(rbac_client, "admin", "Admin!Pass2026")
    logs_res = rbac_client.get("/api/admin/audit-logs")
    assert logs_res.status_code == 200
    logs = logs_res.get_json()

    actions = [l["action"] for l in logs]
    assert "FAILED_LOGIN" in actions
    assert "UNAUTHORIZED_ACCESS" in actions
    assert "LOGIN" in actions


# 12. Demo login endpoint switches role without sending client-side secrets
def test_demo_login_endpoint(rbac_client):
    # Switch to Incident Responder
    res = rbac_client.post("/api/auth/demo-login", json={"role": "INCIDENT_RESPONDER"})
    assert res.status_code == 200
    user_data = res.get_json()["user"]
    assert user_data["role"] == "INCIDENT_RESPONDER"

    # Verify session is authenticated as responder
    me_res = rbac_client.get("/api/auth/me")
    assert me_res.status_code == 200
    assert me_res.get_json()["user"]["role"] == "INCIDENT_RESPONDER"

    # Switch to Viewer
    res_viewer = rbac_client.post("/api/auth/demo-login", json={"role": "VIEWER"})
    assert res_viewer.status_code == 200
    assert res_viewer.get_json()["user"]["role"] == "VIEWER"

