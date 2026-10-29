"""Demo and Testing Fixture API endpoints for AO-03.
Explicitly separated from production/evaluation data paths.
"""

from flask import Blueprint, jsonify
from app.storage import get_storage
from app.ingestion.demo_fixtures import load_demo_data
from app.models.user import UserRole
from app.models.audit import AuditAction
from app.auth.decorators import role_required
from app.auth.audit import log_audit_event

demo_bp = Blueprint("demo", __name__, url_prefix="/api/demo")


@demo_bp.route("/load", methods=["POST"])
@role_required(UserRole.ADMIN)
def load_demo():
    """Loads synthetic demonstration fixtures clearly labeled as SYNTHETIC_DEMO. Admin only."""
    storage = get_storage()
    stats = load_demo_data(storage)
    log_audit_event(
        action=AuditAction.DEMO_ACTION,
        resource_type="FIXTURES",
        result="SUCCESS",
        metadata={"action": "LOAD_DEMO", "stats": stats},
    )
    return jsonify({
        "status": "SUCCESS",
        "message": "Synthetic demonstration fixtures loaded successfully. All records labeled SYNTHETIC_DEMO.",
        "counts": stats,
    })


@demo_bp.route("/reset", methods=["POST"])
@role_required(UserRole.ADMIN)
def reset_data():
    """Wipes all local telemetry and analysis data. Admin only."""
    storage = get_storage()
    storage.clear_all_data()
    log_audit_event(
        action=AuditAction.DEMO_ACTION,
        resource_type="DATABASE",
        result="SUCCESS",
        metadata={"action": "RESET_DATA"},
    )
    return jsonify({
        "status": "SUCCESS",
        "message": "All database records have been cleared.",
    })
