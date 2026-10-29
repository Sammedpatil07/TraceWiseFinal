"""Evidence and Generic Ingestion API endpoints for AO-03.
"""

from flask import Blueprint, jsonify, request
from app.storage import get_storage
from app.models.evidence import EvidenceType, SourceType, NormalizedEvidence, ServiceNode
from app.models.incident import Incident
from app.models.user import UserRole
from app.models.audit import AuditAction
from app.ingestion.generic_adapter import GenericTelemetryIngestor
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
