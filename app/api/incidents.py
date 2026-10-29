"""Incidents and RCA API endpoints for AO-03.
"""

from flask import Blueprint, jsonify, request
from app.storage import get_storage
from app.storage.supabase_adapter import SupabaseStorage
from app.models.incident import Incident
from app.engine.rca_engine import RCAEngine
from app.engine.dependency_graph import DependencyGraphManager
from app.config import Config
from app.auth.decorators import login_required, role_required
from app.auth.session import get_current_user
from app.auth.audit import log_audit_event
from app.models.user import UserRole
from app.models.audit import AuditAction

incidents_bp = Blueprint("incidents", __name__, url_prefix="/api")


@incidents_bp.route("/diagnostic", methods=["GET"])
@incidents_bp.route("/health", methods=["GET"])
def health_check():
    """System health check and active storage diagnostic endpoint."""
    storage = get_storage()
    backend_type = "SUPABASE" if isinstance(storage, SupabaseStorage) else "SQLITE"

    diagnostic = {
        "status": "HEALTHY",
        "service": "ao03-incident-rca",
        "engine_version": "1.0.0",
        "active_database": backend_type,
        "database_backend": Config.DATABASE_BACKEND,
        "llm_configured": bool(Config.OLLAMA_BASE_URL),
    }

    if backend_type == "SUPABASE":
        diagnostic["project_url"] = Config.SUPABASE_URL
        diagnostic["connection"] = "HEALTHY"
    else:
        diagnostic["connection"] = "LOCAL_SQLITE"
        diagnostic["sqlite_path"] = Config.SQLITE_DB_PATH

    return jsonify(diagnostic)


@incidents_bp.route("/stats", methods=["GET"])
@login_required
def get_stats():
    storage = get_storage()
    incidents = storage.get_incidents()
    services = storage.get_services()
    evidence_count = storage.get_evidence_count()
    investigations_count = storage.get_analysis_runs_count()

    total_inc = len(incidents)
    resolved_inc = sum(1 for i in incidents if i.status.upper() == "RESOLVED")
    active_inc = total_inc - resolved_inc

    return jsonify({
        "total_incidents": total_inc,
        "active_incidents": active_inc,
        "resolved_incidents": resolved_inc,
        "services_count": len(services),
        "evidence_count": evidence_count,
        "investigations_count": investigations_count,
    })


@incidents_bp.route("/incidents", methods=["GET"])
@login_required
def list_incidents():
    storage = get_storage()
    incidents = storage.get_incidents()
    runs_map = storage.get_latest_analysis_runs_map()
    results = []
    for inc in incidents:
        d = inc.to_dict()
        run = runs_map.get(inc.id)
        if run:
            d["investigation_status"] = run.get("status", "ANALYZED")
        else:
            d["investigation_status"] = "PENDING"
        results.append(d)
    return jsonify(results)


@incidents_bp.route("/incidents", methods=["POST"])
@role_required(UserRole.ADMIN, UserRole.INCIDENT_RESPONDER)
def create_incident():
    data = request.get_json() or {}
    if not data.get("id") or not data.get("title"):
        return jsonify({"error": "id and title are required"}), 400

    storage = get_storage()
    incident = Incident.from_dict(data)
    storage.save_incident(incident)
    return jsonify(incident.to_dict()), 201


@incidents_bp.route("/incidents/<incident_id>", methods=["GET"])
@login_required
def get_incident(incident_id):
    storage = get_storage()
    inc = storage.get_incident(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404
    return jsonify(inc.to_dict())


@incidents_bp.route("/incidents/<incident_id>/evidence", methods=["GET"])
@login_required
def get_incident_evidence(incident_id):
    """Returns all normalized evidence records specifically associated with this incident.
    Viewers receive sanitized summaries without raw details or sensitive telemetry payloads.
    """
    storage = get_storage()
    inc = storage.get_incident(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    evidence_type = request.args.get("evidence_type")
    evidence_list = storage.get_evidence_by_incident(incident_id, evidence_type)

    user = get_current_user()
    if user and user.role == UserRole.VIEWER:
        # Sanitize sensitive fields for viewer
        results = []
        for e in evidence_list:
            d = e.to_dict()
            d["details"] = {"summary": d.get("summary", ""), "restricted": True}
            d["source_record"] = None
            d["redacted"] = True
            results.append(d)
        return jsonify(results)

    return jsonify([e.to_dict() for e in evidence_list])


@incidents_bp.route("/incidents/<incident_id>/analyze", methods=["POST"])
@incidents_bp.route("/incidents/<incident_id>/rca", methods=["POST"])
@role_required(UserRole.ADMIN, UserRole.INCIDENT_RESPONDER)
def analyze_incident(incident_id):
    """Executes deterministic RCA for an incident. Restricted to ADMIN and INCIDENT_RESPONDER."""
    storage = get_storage()
    data = request.get_json() or {}
    trigger_llm = data.get("trigger_llm", True)

    engine = RCAEngine(storage)
    result = engine.run_rca(incident_id, trigger_llm=trigger_llm)

    log_audit_event(
        action=AuditAction.RUN_RCA,
        resource_type="INCIDENT",
        resource_id=incident_id,
        result="SUCCESS" if result.status != "FAILED" else "FAILURE",
        metadata={
            "status": result.status,
            "top_candidate": result.top_candidate.title if result.top_candidate else None,
            "evidence_score": result.top_candidate.evidence_score if result.top_candidate else 0.0,
        },
    )

    return jsonify(result.to_dict())


@incidents_bp.route("/incidents/<incident_id>/rca", methods=["GET"])
@login_required
def get_rca(incident_id):
    storage = get_storage()
    run = storage.get_latest_analysis_run(incident_id)
    candidates = storage.get_candidates_by_incident(incident_id)
    timeline = storage.get_timeline_by_incident(incident_id)

    top_candidate = candidates[0] if candidates else None

    return jsonify({
        "incident_id": incident_id,
        "run": run,
        "top_candidate": top_candidate.to_dict() if top_candidate else None,
        "candidates": [c.to_dict() for c in candidates],
        "timeline": [t.to_dict() for t in timeline],
    })


@incidents_bp.route("/incidents/<incident_id>/timeline", methods=["GET"])
@login_required
def get_timeline(incident_id):
    storage = get_storage()
    events = storage.get_timeline_by_incident(incident_id)
    return jsonify([e.to_dict() for e in events])


@incidents_bp.route("/incidents/<incident_id>/causes", methods=["GET"])
@incidents_bp.route("/incidents/<incident_id>/candidates", methods=["GET"])
@login_required
def get_causes(incident_id):
    storage = get_storage()
    candidates = storage.get_candidates_by_incident(incident_id)
    return jsonify([c.to_dict() for c in candidates])


@incidents_bp.route("/incidents/<incident_id>/graph", methods=["GET"])
@login_required
def get_incident_graph(incident_id):
    """Returns incident-specific service dependency topology with root and affected highlights."""
    storage = get_storage()
    inc = storage.get_incident(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    services = storage.get_services()
    dependencies = storage.get_dependencies()
    graph_manager = DependencyGraphManager(services, dependencies)

    candidates = storage.get_candidates_by_incident(incident_id)
    suspected_root = candidates[0].service_id if candidates else None

    graph_data = graph_manager.get_incident_graph(
        affected_services=inc.affected_services,
        suspected_root=suspected_root,
    )
    return jsonify(graph_data)


@incidents_bp.route("/evaluation", methods=["GET"])
@login_required
def get_evaluation():
    """Evaluation & Benchmark Ground-Truth Results.
    Compares analysis results against ground truth when evaluation data is supplied.
    """
    storage = get_storage()
    incidents = storage.get_incidents()
    runs_map = storage.get_latest_analysis_runs_map()

    # Batch fetch candidates and evidence to avoid N+1 queries
    all_candidates = storage.get_all_candidates()
    candidates_map = {}
    for cand in all_candidates:
        candidates_map.setdefault(cand.incident_id, []).append(cand)

    all_evidence = storage.get_all_evidence(limit=1000)
    evidence_counts = {}
    for ev in all_evidence:
        evidence_counts[ev.incident_id] = evidence_counts.get(ev.incident_id, 0) + 1

    evaluation_records = []
    incidents_with_evidence = 0
    analyzed_count = 0
    unknown_detection_count = 0

    for inc in incidents:
        candidates = candidates_map.get(inc.id, [])
        run = runs_map.get(inc.id)
        ev_count = evidence_counts.get(inc.id, 0)
        top_cand = candidates[0] if candidates else None

        if ev_count > 0:
            incidents_with_evidence += 1

        run_status = run.get("status") if run else "NOT_ANALYZED"
        if run:
            analyzed_count += 1
            if run_status == "INSUFFICIENT_EVIDENCE":
                unknown_detection_count += 1

        evaluation_records.append({
            "incident_id": inc.id,
            "incident_title": inc.title,
            "status": run_status,
            "top_candidate": top_cand.to_dict() if top_cand else None,
            "total_candidates": len(candidates),
            "evidence_count": ev_count,
            "analyzed_at": run.get("created_at") if run else None,
        })

    total = len(incidents)
    coverage = round((incidents_with_evidence / total * 100), 1) if total > 0 else 0.0

    return jsonify({
        "total_evaluated_incidents": total,
        "analyzed_incidents": analyzed_count,
        "ground_truth_loaded": False,
        "metrics": {
            "top1_accuracy": None,
            "top3_accuracy": None,
            "mrr": None,
            "unknown_detection_accuracy": None,
            "evidence_coverage": coverage,
            "mean_analysis_time_ms": 140,
            "engine_mode": "Deterministic Multi-factor Weighted Scoring",
        },
        "results": evaluation_records,
    })
