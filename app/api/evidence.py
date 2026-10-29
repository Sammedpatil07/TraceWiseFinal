"""Evidence and Generic Ingestion API endpoints for AO-03.
"""

import hashlib
from typing import Tuple, Optional, Set
from flask import Blueprint, jsonify, request
from app.storage import get_storage
from app.models.evidence import EvidenceType, SourceType, NormalizedEvidence, ServiceNode
from app.models.incident import Incident
from app.models.user import UserRole
from app.models.audit import AuditAction
from app.ingestion.generic_adapter import GenericTelemetryIngestor
from app.ingestion.csv_ingestor import CSVLogIngestor
from app.engine.timeline import generate_incident_timeline
from app.auth.decorators import login_required, role_required
from app.auth.session import get_current_user
from app.auth.audit import log_audit_event

evidence_bp = Blueprint("evidence", __name__, url_prefix="/api")



@evidence_bp.route("/evidence", methods=["GET"])
@login_required
def list_evidence():
    """Lists evidence items. Viewers receive sanitized records with raw details redacted."""
    storage = get_storage()
    incident_id = request.args.get("incident_id")
    evidence_type = request.args.get("evidence_type")
    limit = int(request.args.get("limit", 200))

    if incident_id:
        evidence_list = storage.get_evidence_by_incident(incident_id, evidence_type)
    else:
        evidence_list = storage.get_all_evidence(limit=limit, evidence_type=evidence_type)

    user = get_current_user()
    if user and user.role == UserRole.VIEWER:
        sanitized = []
        for e in evidence_list:
            d = e.to_dict()
            # Redact raw metadata/details for Viewer
            d["details"] = {"summary": d.get("summary", ""), "restricted": True}
            d["source_record"] = None
            d["redacted"] = True
            sanitized.append(d)
        return jsonify(sanitized)

    return jsonify([e.to_dict() for e in evidence_list])


@evidence_bp.route("/evidence/<evidence_id>", methods=["GET"])
@role_required(UserRole.ADMIN, UserRole.INCIDENT_RESPONDER)
def get_evidence(evidence_id):
    """Deep raw telemetry inspection. Restricted to ADMIN and INCIDENT_RESPONDER."""
    storage = get_storage()
    ev = storage.get_evidence_by_id(evidence_id)
    if not ev:
        return jsonify({"error": "Evidence not found"}), 404
    return jsonify(ev.to_dict())


@evidence_bp.route("/ingest", methods=["POST"])
@role_required(UserRole.ADMIN)
def ingest_telemetry():
    """Universal ingestion endpoint supporting JSON, JSONL, CSV, and schema mappings.
    Malformed records do not crash the batch and are reported in the response.
    """
    data = request.get_json(silent=True)
    format_hint = request.args.get("format")
    if not data:
        # Check for raw text data (CSV or JSONL uploaded as text)
        raw_text = request.get_data(as_text=True)
        incident_id = request.args.get("incident_id", "INC-DEFAULT")
        payload = raw_text
        custom_mapping = None
        source_type_str = "ORGANIZER"
        evidence_type = request.args.get("evidence_type")
    else:
        incident_id = data.get("incident_id") or request.args.get("incident_id")
        evidence_type = data.get("evidence_type") or data.get("telemetry_type")
        payload = data.get("records") if "records" in data else (data.get("data") if "data" in data else data.get("content", data))
        custom_mapping = data.get("schema_mapping")
        source_type_str = str(data.get("source_type", "ORGANIZER")).upper()
        if data.get("format"):
            format_hint = data.get("format")

    if not incident_id:
        return jsonify({"error": "incident_id is required"}), 400

    source_type = SourceType.ORGANIZER if source_type_str != "SYNTHETIC_DEMO" else SourceType.SYNTHETIC_DEMO

    # Parse and normalize via GenericTelemetryIngestor
    ingestor = GenericTelemetryIngestor(schema_mapping=custom_mapping)
    normalized_list, report = ingestor.parse(
        raw_data=payload,
        incident_id=incident_id,
        source_type=source_type,
        evidence_type_hint=evidence_type,
        format_hint=format_hint,
    )

    storage = get_storage()

    # Ensure parent incident exists in storage
    inc = storage.get_incident(incident_id)
    if not inc:
        storage.save_incident(Incident(
            id=incident_id,
            title=f"Incident {incident_id}",
            description="Auto-registered from ingested telemetry stream",
            status="RESOLVED",
            severity="MEDIUM",
            affected_services=[],
        ))

    # Ensure referenced services exist in storage
    if normalized_list:
        existing_services = {s.id for s in storage.get_services()}
        for ev in normalized_list:
            if ev.service and ev.service not in existing_services:
                storage.save_service(ServiceNode(
                    id=ev.service,
                    name=ev.service.replace("-", " ").title(),
                    tier="service",
                    description="Auto-discovered service node",
                ))
                existing_services.add(ev.service)

        storage.save_evidence_batch(normalized_list)

    status_code = 201 if report["ingested_count"] > 0 else (400 if report["status"] == "FAILED" else 200)

    log_audit_event(
        action=AuditAction.INGEST_TELEMETRY,
        resource_type="TELEMETRY",
        resource_id=incident_id,
        result="SUCCESS" if report["status"] != "FAILED" else "FAILURE",
        metadata={
            "ingested_count": report["ingested_count"],
            "failed_count": report["failed_count"],
            "status": report["status"],
        },
    )

    return jsonify({
        "status": report["status"],
        "incident_id": incident_id,
        "total_received": report["total_received"],
        "ingested_count": report["ingested_count"],
        "failed_count": report["failed_count"],
        "errors": report["errors"],
        "warnings": report["warnings"],
    }), status_code


def _extract_upload_content(req) -> Tuple[Optional[str], str, int, Optional[str]]:
    """Extracts raw text, filename, file_size, and optional error from multipart, json, or stream."""
    if req.files and "file" in req.files:
        file = req.files["file"]
        filename = file.filename or "uploaded_logs.csv"
        content_bytes = file.read()
        file_size = len(content_bytes)

        if file_size > CSVLogIngestor.MAX_FILE_SIZE_BYTES:
            return None, filename, file_size, f"File exceeds the {CSVLogIngestor.MAX_FILE_SIZE_BYTES // (1024*1024)} MB maximum limit."

        if not filename.lower().endswith(".csv"):
            return None, filename, file_size, "Invalid file format. Only .csv files are supported."

        try:
            text = content_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content_bytes.decode("latin-1")
            except Exception as e:
                return None, filename, file_size, f"Unable to decode CSV file as UTF-8: {str(e)}"

        return text, filename, file_size, None

    if req.is_json:
        data = req.get_json(silent=True) or {}
        text = data.get("csv_content") or data.get("content") or data.get("data")
        filename = data.get("filename", "payload.csv")
        if not text:
            return None, filename, 0, "No CSV content provided in request JSON body."
        raw_bytes = text.encode("utf-8")
        if len(raw_bytes) > CSVLogIngestor.MAX_FILE_SIZE_BYTES:
            return None, filename, len(raw_bytes), f"Content exceeds the {CSVLogIngestor.MAX_FILE_SIZE_BYTES // (1024*1024)} MB limit."
        return text, filename, len(raw_bytes), None

    raw_text = req.get_data(as_text=True)
    if raw_text and raw_text.strip():
        filename = req.args.get("filename", "stream.csv")
        raw_bytes = raw_text.encode("utf-8")
        if len(raw_bytes) > CSVLogIngestor.MAX_FILE_SIZE_BYTES:
            return None, filename, len(raw_bytes), f"Content exceeds the {CSVLogIngestor.MAX_FILE_SIZE_BYTES // (1024*1024)} MB limit."
        return raw_text, filename, len(raw_bytes), None

    return None, "empty.csv", 0, "No file or CSV content provided. Please select a .csv file."


def _get_existing_signatures(storage, incident_id: str) -> Set[str]:
    """Retrieves existing deduplication signatures for the incident to prevent duplicate imports."""
    signatures = set()
    try:
        existing = storage.get_evidence_by_incident(incident_id)
        for ev in existing:
            if ev.metadata and ev.metadata.get("signature"):
                signatures.add(ev.metadata["signature"])
            else:
                sig_raw = f"{incident_id}_{ev.service}_{ev.timestamp}_{ev.message[:120]}"
                signatures.add(hashlib.sha256(sig_raw.encode()).hexdigest())
    except Exception:
        pass
    return signatures


@evidence_bp.route("/incidents/<incident_id>/upload/preview", methods=["POST"])
@evidence_bp.route("/evidence/upload/preview", methods=["POST"])
@role_required(UserRole.ADMIN, UserRole.INCIDENT_RESPONDER)
def preview_csv_upload(incident_id: Optional[str] = None):
    """Validates and previews CSV log records for an incident WITHOUT persisting to storage."""
    target_incident_id = incident_id or request.form.get("incident_id") or request.args.get("incident_id")
    if not target_incident_id:
        return jsonify({"error": "incident_id is required"}), 400

    storage = get_storage()
    inc = storage.get_incident(target_incident_id)
    if not inc:
        return jsonify({"error": f"Incident '{target_incident_id}' not found."}), 404

    csv_text, filename, file_size, extract_error = _extract_upload_content(request)
    if extract_error:
        status_code = 413 if "exceeds" in extract_error.lower() else 400
        return jsonify({"error": extract_error, "filename": filename, "file_size": file_size}), status_code

    existing_signatures = _get_existing_signatures(storage, target_incident_id)

    ingestor = CSVLogIngestor()
    report = ingestor.parse_csv_stream(
        csv_text=csv_text,
        incident_id=target_incident_id,
        existing_signatures=existing_signatures,
        source_file=filename,
    )

    return jsonify({
        "status": report["status"],
        "incident_id": target_incident_id,
        "filename": filename,
        "file_size": file_size,
        "total_rows": report["total_rows"],
        "valid_count": report["valid_count"],
        "invalid_count": report["invalid_count"],
        "duplicate_count": report["duplicate_count"],
        "preview_rows": report["preview_rows"],
        "row_errors": report["row_errors"][:50],
        "warnings": report["warnings"],
        "services_detected": report["services_detected"],
    }), 200


@evidence_bp.route("/incidents/<incident_id>/upload/commit", methods=["POST"])
@evidence_bp.route("/evidence/upload/commit", methods=["POST"])
@role_required(UserRole.ADMIN, UserRole.INCIDENT_RESPONDER)
def commit_csv_upload(incident_id: Optional[str] = None):
    """Permanently commits validated CSV log records to incident storage and updates timeline."""
    target_incident_id = incident_id or request.form.get("incident_id") or request.args.get("incident_id")
    if not target_incident_id:
        return jsonify({"error": "incident_id is required"}), 400

    storage = get_storage()
    inc = storage.get_incident(target_incident_id)
    if not inc:
        return jsonify({"error": f"Incident '{target_incident_id}' not found."}), 404

    csv_text, filename, file_size, extract_error = _extract_upload_content(request)
    if extract_error:
        status_code = 413 if "exceeds" in extract_error.lower() else 400
        return jsonify({"error": extract_error}), status_code

    existing_signatures = _get_existing_signatures(storage, target_incident_id)

    ingestor = CSVLogIngestor()
    report = ingestor.parse_csv_stream(
        csv_text=csv_text,
        incident_id=target_incident_id,
        existing_signatures=existing_signatures,
        source_file=filename,
    )

    if report["valid_count"] == 0:
        return jsonify({
            "status": "FAILED",
            "incident_id": target_incident_id,
            "filename": filename,
            "error": "No valid new evidence records found to import.",
            "total_rows": report["total_rows"],
            "invalid_count": report["invalid_count"],
            "duplicate_count": report["duplicate_count"],
            "row_errors": report["row_errors"][:20],
        }), 400

    # Auto-register newly discovered service nodes in storage
    try:
        existing_services = {s.id for s in storage.get_services()}
        for svc_id in report["services_detected"]:
            if svc_id and svc_id not in existing_services and svc_id != "unassigned-service":
                storage.save_service(ServiceNode(
                    id=svc_id,
                    name=svc_id.replace("-", " ").replace("_", " ").title(),
                    tier="service",
                    description=f"Auto-discovered from CSV log import ({filename})",
                ))
                existing_services.add(svc_id)
    except Exception as e:
        pass

    # Save evidence batch to active storage (SQLite or Supabase)
    valid_records = report["normalized_records"]
    storage.save_evidence_batch(valid_records)

    # Regenerate chronological timeline for the incident
    try:
        all_incident_evidence = storage.get_evidence_by_incident(target_incident_id)
        timeline_events = generate_incident_timeline(all_incident_evidence)
        if timeline_events:
            storage.save_timeline_events_batch(timeline_events)
    except Exception:
        pass

    # Record security audit log
    log_audit_event(
        action=AuditAction.INGEST_TELEMETRY,
        resource_type="INCIDENT_CSV_UPLOAD",
        resource_id=target_incident_id,
        result="SUCCESS",
        metadata={
            "filename": filename,
            "file_size": file_size,
            "total_rows": report["total_rows"],
            "accepted_count": len(valid_records),
            "rejected_count": report["invalid_count"],
            "duplicate_count": report["duplicate_count"],
            "skipped_count": 0,
        },
    )

    return jsonify({
        "status": "SUCCESS",
        "incident_id": target_incident_id,
        "filename": filename,
        "total_records": report["total_rows"],
        "accepted_count": len(valid_records),
        "rejected_count": report["invalid_count"],
        "duplicate_count": report["duplicate_count"],
        "skipped_count": 0,
        "message": f"Successfully ingested {len(valid_records)} evidence records into incident {target_incident_id}.",
        "services_detected": report["services_detected"],
    }), 201

