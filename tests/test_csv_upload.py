"""Automated tests for TraceWise AO-03 CSV Log Upload, Validation, Ingestion, and RCA Integration.
"""

import io
import pytest
from app import create_app
from app.config import Config
from app.storage import reset_storage, get_storage
from app.models.user import UserRole
from app.models.incident import Incident
from app.ingestion.csv_ingestor import CSVLogIngestor
from app.ingestion.demo_fixtures import load_demo_data
from app.engine.rca_engine import RCAEngine


@pytest.fixture
def test_client(tmp_path):
    reset_storage()
    Config.DATABASE_BACKEND = "sqlite"
    Config.STORAGE_BACKEND = "sqlite"
    Config.SQLITE_DB_PATH = str(tmp_path / "test_csv_upload.db")
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-csv"

    storage = get_storage()
    load_demo_data(storage)

    with app.test_client() as client:
        yield client

    reset_storage()


def login_as(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# ============================================================================
# 1. CSVLogIngestor Unit Tests: Parsing, Quotes, Escapes, Encodings
# ============================================================================

def test_csv_parser_standard_and_bom():
    """Verify standard CSV and UTF-8 BOM parsing."""
    ingestor = CSVLogIngestor()

    csv_content = "\ufefftimestamp,service,severity,message\n2026-03-15T10:00:00Z,payment-service,ERROR,Database connection pool exhausted\n"
    report = ingestor.parse_csv_stream(csv_content, incident_id="INC-TEST-001")

    assert report["status"] == "VALID"
    assert report["total_rows"] == 1
    assert report["valid_count"] == 1
    assert len(report["normalized_records"]) == 1

    rec = report["normalized_records"][0]
    assert rec.service == "payment-service"
    assert rec.severity.value == "HIGH"
    assert rec.timestamp == "2026-03-15T10:00:00Z"
    assert "Database connection pool exhausted" in rec.message


def test_csv_parser_quoted_commas_and_escaped_quotes():
    """Verify handling of commas inside quoted strings and escaped quotes."""
    ingestor = CSVLogIngestor()

    csv_content = (
        'timestamp,service,severity,message\n'
        '2026-03-15T10:01:00Z,order-service,CRITICAL,"Failed to process order #102, timeout after 5000ms, retrying..."\n'
        '2026-03-15T10:02:00Z,auth-service,WARN,"Invalid JSON payload in header ""X-Trace-Auth"""\n'
    )
    report = ingestor.parse_csv_stream(csv_content, incident_id="INC-TEST-001")

    assert report["status"] == "VALID"
    assert report["total_rows"] == 2
    assert report["valid_count"] == 2

    records = report["normalized_records"]
    assert "timeout after 5000ms, retrying..." in records[0].message
    assert 'header "X-Trace-Auth"' in records[1].message



def test_csv_parser_crlf_windows_and_unix_line_endings():
    """Verify handling of both Windows CRLF and Unix LF line breaks."""
    ingestor = CSVLogIngestor()

    # Windows CRLF
    csv_crlf = "timestamp,service,severity,message\r\n2026-03-15T10:00:00Z,payment-service,INFO,Order created\r\n2026-03-15T10:01:00Z,payment-service,HIGH,Payment gateway 504\r\n"
    report_crlf = ingestor.parse_csv_stream(csv_crlf, incident_id="INC-TEST-001")
    assert report_crlf["valid_count"] == 2

    # Unix LF
    csv_lf = "timestamp,service,severity,message\n2026-03-15T10:00:00Z,payment-service,INFO,Order created\n2026-03-15T10:01:00Z,payment-service,HIGH,Payment gateway 504\n"
    report_lf = ingestor.parse_csv_stream(csv_lf, incident_id="INC-TEST-001")
    assert report_lf["valid_count"] == 2


def test_csv_parser_sensitive_data_redaction():
    """Verify automatic redaction of bearer tokens and passwords in messages."""
    ingestor = CSVLogIngestor()

    csv_content = (
        'timestamp,service,severity,message\n'
        '2026-03-15T10:00:00Z,gateway,ERROR,"Failed request Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-ID with password=SecretPassword123!"\n'
    )
    report = ingestor.parse_csv_stream(csv_content, incident_id="INC-TEST-001")

    assert report["valid_count"] == 1
    msg = report["normalized_records"][0].message
    assert "SecretPassword123!" not in msg
    assert "password=[REDACTED]" in msg
    assert "Bearer [REDACTED]" in msg


def test_csv_parser_formula_injection_defense():
    """Verify that dangerous spreadsheet formula prefixes (=, +, -, @) are neutralized."""
    ingestor = CSVLogIngestor()

    csv_content = (
        'timestamp,service,severity,message\n'
        '2026-03-15T10:00:00Z,worker,INFO,=cmd|\' /C calc\'!A0\n'
        '2026-03-15T10:01:00Z,worker,INFO,@SUM(1+1)\n'
    )
    report = ingestor.parse_csv_stream(csv_content, incident_id="INC-TEST-001")

    assert report["valid_count"] == 2
    for rec in report["normalized_records"]:
        assert rec.message.startswith("'")


def test_csv_parser_deduplication():
    """Verify intra-batch and cross-storage duplicate detection."""
    ingestor = CSVLogIngestor()

    # Intra-batch duplicate
    csv_content = (
        'timestamp,service,severity,message\n'
        '2026-03-15T10:00:00Z,payment-service,ERROR,Identical error message\n'
        '2026-03-15T10:00:00Z,payment-service,ERROR,Identical error message\n'
    )
    report = ingestor.parse_csv_stream(csv_content, incident_id="INC-TEST-001")

    assert report["total_rows"] == 2
    assert report["valid_count"] == 1
    assert report["duplicate_count"] == 1
    assert report["status"] == "PARTIAL_VALID"


def test_csv_parser_malformed_row_isolation():
    """Verify that malformed rows with bad timestamps do not crash the valid rows."""
    ingestor = CSVLogIngestor()

    csv_content = (
        'timestamp,service,severity,message\n'
        '2026-03-15T10:00:00Z,payment-service,INFO,Valid row 1\n'
        'NOT_A_TIMESTAMP,payment-service,ERROR,Malformed timestamp row\n'
        '2026-03-15T10:02:00Z,payment-service,INFO,Valid row 2\n'
    )
    report = ingestor.parse_csv_stream(csv_content, incident_id="INC-TEST-001")

    assert report["total_rows"] == 3
    assert report["valid_count"] == 2
    assert report["invalid_count"] == 1
    assert len(report["row_errors"]) == 1
    assert report["row_errors"][0]["row"] == 3  # Header is row 1, malformed is row 3


# ============================================================================
# 2. RBAC & Security Tests on CSV Upload Endpoints
# ============================================================================

def test_unauthenticated_upload_blocked(test_client):
    """Unauthenticated users must be blocked with 401."""
    res_preview = test_client.post("/api/incidents/INC-2026-001/upload/preview")
    assert res_preview.status_code == 401

    res_commit = test_client.post("/api/incidents/INC-2026-001/upload/commit")
    assert res_commit.status_code == 401


def test_viewer_upload_forbidden(test_client):
    """Viewers cannot preview or commit CSV uploads (403 Forbidden)."""
    login_as(test_client, "auditor_viewer", "Viewer!Pass2026")

    csv_bytes = b"timestamp,service,severity,message\n2026-03-15T10:00:00Z,svc,INFO,msg\n"
    res_preview = test_client.post(
        "/api/incidents/INC-2026-001/upload/preview",
        data={"file": (io.BytesIO(csv_bytes), "test1.csv")},
        content_type="multipart/form-data"
    )
    assert res_preview.status_code == 403

    res_commit = test_client.post(
        "/api/incidents/INC-2026-001/upload/commit",
        data={"file": (io.BytesIO(csv_bytes), "test2.csv")},
        content_type="multipart/form-data"
    )
    assert res_commit.status_code == 403



# ============================================================================
# 3. End-to-End Workflow: Preview -> Commit -> Persistence -> RCA
# ============================================================================

def test_preview_does_not_persist_records(test_client):
    """Previewing CSV logs must not mutate or persist evidence to storage."""
    login_as(test_client, "sre_responder", "Sre!Pass2026")

    storage = get_storage()
    count_before = len(storage.get_evidence_by_incident("INC-2026-001"))

    csv_data = b"timestamp,service,severity,message\n2026-03-15T10:00:00Z,payment-service,HIGH,Preview-only message\n"
    res = test_client.post(
        "/api/incidents/INC-2026-001/upload/preview",
        data={"file": (io.BytesIO(csv_data), "preview_test.csv")},
        content_type="multipart/form-data"
    )
    assert res.status_code == 200
    report = res.get_json()
    assert report["valid_count"] == 1
    assert len(report["preview_rows"]) == 1

    # Verify no records were persisted in storage
    count_after = len(storage.get_evidence_by_incident("INC-2026-001"))
    assert count_after == count_before


def test_commit_persists_records_and_updates_rca(test_client):
    """Committing valid records persists them, logs audit, and updates RCA workflow."""
    login_as(test_client, "sre_responder", "Sre!Pass2026")

    storage = get_storage()
    count_before = len(storage.get_evidence_by_incident("INC-2026-001"))

    csv_content = (
        b"timestamp,service,severity,message,trace_id\n"
        b"2026-03-15T10:15:00Z,payment-service,CRITICAL,High memory threshold reached 98%,trc-mem-001\n"
        b"2026-03-15T10:15:30Z,payment-service,CRITICAL,Payment worker OOM killed by kernel,trc-mem-001\n"
        b"2026-03-15T10:16:00Z,notification-service,ERROR,Failed to deliver payment webhook,trc-mem-002\n"
    )

    commit_res = test_client.post(
        "/api/incidents/INC-2026-001/upload/commit",
        data={"file": (io.BytesIO(csv_content), "production_incident_logs.csv")},
        content_type="multipart/form-data"
    )
    assert commit_res.status_code == 201
    result = commit_res.get_json()
    assert result["status"] == "SUCCESS"
    assert result["accepted_count"] == 3
    assert result["rejected_count"] == 0
    assert result["duplicate_count"] == 0

    # 1. Verify records persisted in storage
    count_after = len(storage.get_evidence_by_incident("INC-2026-001"))
    assert count_after == count_before + 3

    # 2. Verify audit log entry created
    audit_logs = storage.get_audit_logs()
    upload_audits = [a for a in audit_logs if a.resource_type == "INCIDENT_CSV_UPLOAD"]
    assert len(upload_audits) > 0
    assert upload_audits[0].metadata["accepted_count"] == 3

    # 3. Verify newly imported evidence is immediately visible in evidence API
    ev_res = test_client.get("/api/incidents/INC-2026-001/evidence")
    assert ev_res.status_code == 200
    ev_items = ev_res.get_json()
    messages = [e["message"] for e in ev_items]
    assert any("High memory threshold reached 98%" in m for m in messages)

    # 4. Verify RCA execution includes newly imported evidence in analysis
    rca_res = test_client.post("/api/incidents/INC-2026-001/rca", json={"trigger_llm": False})
    assert rca_res.status_code == 200
    rca_data = rca_res.get_json()
    assert rca_data["status"] == "SUCCESS"
    assert rca_data["top_candidate"] is not None

    # Check that the timeline includes new events
    timeline_res = test_client.get("/api/incidents/INC-2026-001/timeline")
    assert timeline_res.status_code == 200
    timeline = timeline_res.get_json()
    assert len(timeline) > 0


def test_commit_duplicate_detection_on_reupload(test_client):
    """Re-uploading the same CSV log file detects duplicates and skips them without creating duplicates."""
    login_as(test_client, "admin", "Admin!Pass2026")

    storage = get_storage()

    csv_content = (
        b"timestamp,service,severity,message\n"
        b"2026-03-15T11:00:00Z,inventory-service,HIGH,Stock lock contention detected\n"
    )

    # First commit
    res1 = test_client.post(
        "/api/incidents/INC-2026-001/upload/commit",
        data={"file": (io.BytesIO(csv_content), "inventory.csv")},
        content_type="multipart/form-data"
    )
    assert res1.status_code == 201
    assert res1.get_json()["accepted_count"] == 1

    # Second commit with same file -> should be rejected as duplicates with 400 or duplicate count
    res2 = test_client.post(
        "/api/incidents/INC-2026-001/upload/commit",
        data={"file": (io.BytesIO(csv_content), "inventory.csv")},
        content_type="multipart/form-data"
    )
    assert res2.status_code == 400
    err = res2.get_json()
    assert err["duplicate_count"] == 1
    assert "No valid new evidence records found" in err["error"]


def test_upload_non_csv_rejected(test_client):
    """Uploading non-csv files (e.g. .exe or .json) is rejected with 400."""
    login_as(test_client, "sre_responder", "Sre!Pass2026")

    res = test_client.post(
        "/api/incidents/INC-2026-001/upload/preview",
        data={"file": (io.BytesIO(b"binary executable data"), "malicious.exe")},
        content_type="multipart/form-data"
    )
    assert res.status_code == 400
    assert "Only .csv files are supported" in res.get_json()["error"]
