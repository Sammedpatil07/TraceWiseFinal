"""Admin and User Management API Blueprint for TraceWise AO-03.
Strictly restricted to users with the ADMIN role.
"""

import uuid
from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

from app.storage import get_storage
from app.models.user import User, UserRole
from app.models.audit import AuditAction
from app.auth.decorators import role_required, login_required
from app.auth.audit import log_audit_event
from app.auth.session import get_current_user

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@admin_bp.route("/users", methods=["GET"])
@role_required(UserRole.ADMIN)
def list_users():
    """Returns list of registered users. Passwords are never included."""
    storage = get_storage()
    users = storage.get_all_users()
    return jsonify([u.to_dict(include_sensitive=False) for u in users])


@admin_bp.route("/users", methods=["POST"])
@role_required(UserRole.ADMIN)
def create_user():
    """Creates a new user with a hashed password and assigned RBAC role."""
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    role_raw = str(data.get("role", UserRole.VIEWER)).strip()
    email = data.get("email")

    if not username or not password:
        return jsonify({"error": "Username and password are required.", "code": "BAD_REQUEST"}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters.", "code": "WEAK_PASSWORD"}), 400

    storage = get_storage()
    existing = storage.get_user_by_username(username)
    if existing:
        return jsonify({"error": f"Username '{username}' is already taken.", "code": "DUPLICATE_USERNAME"}), 409

    role = UserRole.normalize(role_raw)
    new_user = User(
        id=f"usr_{uuid.uuid4().hex[:10]}",
        username=username,
        password_hash=generate_password_hash(password),
        role=role,
        email=email,
        is_active=True,
    )

    storage.save_user(new_user)

    log_audit_event(
        action=AuditAction.CREATE_USER,
        resource_type="USER",
        resource_id=new_user.id,
        result="SUCCESS",
        metadata={"created_username": new_user.username, "assigned_role": new_user.role},
    )

    return jsonify({
        "status": "SUCCESS",
        "message": f"User '{new_user.username}' created successfully.",
        "user": new_user.to_dict(include_sensitive=False),
    }), 201


@admin_bp.route("/users/<user_id>/role", methods=["PUT"])
@role_required(UserRole.ADMIN)
def update_user_role(user_id):
    """Updates an existing user's role."""
    data = request.get_json(silent=True) or {}
    new_role_raw = data.get("role")
    if not new_role_raw:
        return jsonify({"error": "role field is required.", "code": "BAD_REQUEST"}), 400

    storage = get_storage()
    target_user = storage.get_user_by_id(user_id)
    if not target_user:
        return jsonify({"error": "User not found.", "code": "NOT_FOUND"}), 404

    current_user = get_current_user()
    if current_user and current_user.id == target_user.id and target_user.role == UserRole.ADMIN and new_role_raw != UserRole.ADMIN:
        return jsonify({"error": "Admins cannot demote their own account.", "code": "FORBIDDEN"}), 403

    normalized_role = UserRole.normalize(new_role_raw)
    success = storage.update_user_role(user_id, normalized_role)

    if success:
        log_audit_event(
            action=AuditAction.UPDATE_ROLE,
            resource_type="USER",
            resource_id=user_id,
            result="SUCCESS",
            metadata={"previous_role": target_user.role, "new_role": normalized_role},
        )
        updated = storage.get_user_by_id(user_id)
        return jsonify({
            "status": "SUCCESS",
            "message": f"User role updated to {normalized_role}.",
            "user": updated.to_dict(include_sensitive=False) if updated else None,
        })
    return jsonify({"error": "Failed to update role.", "code": "SERVER_ERROR"}), 500


@admin_bp.route("/users/<user_id>/status", methods=["PUT"])
@role_required(UserRole.ADMIN)
def toggle_user_status(user_id):
    """Enables or disables a user account."""
    data = request.get_json(silent=True) or {}
    if "is_active" not in data:
        return jsonify({"error": "is_active boolean field is required.", "code": "BAD_REQUEST"}), 400

    is_active = bool(data["is_active"])
    storage = get_storage()
    target_user = storage.get_user_by_id(user_id)
    if not target_user:
        return jsonify({"error": "User not found.", "code": "NOT_FOUND"}), 404

    current_user = get_current_user()
    if current_user and current_user.id == target_user.id and not is_active:
        return jsonify({"error": "Admins cannot disable their own account.", "code": "FORBIDDEN"}), 403

    success = storage.update_user_status(user_id, is_active)
    if success:
        log_audit_event(
            action=AuditAction.TOGGLE_USER_STATUS,
            resource_type="USER",
            resource_id=user_id,
            result="SUCCESS",
            metadata={"username": target_user.username, "is_active": is_active},
        )
        updated = storage.get_user_by_id(user_id)
        return jsonify({
            "status": "SUCCESS",
            "message": f"User {'enabled' if is_active else 'disabled'} successfully.",
            "user": updated.to_dict(include_sensitive=False) if updated else None,
        })
    return jsonify({"error": "Failed to update status.", "code": "SERVER_ERROR"}), 500


@admin_bp.route("/audit-logs", methods=["GET"])
@role_required(UserRole.ADMIN, UserRole.INCIDENT_RESPONDER)
def get_audit_logs():
    """Returns security audit logs. Viewers are blocked (403)."""
    current_user = get_current_user()
    limit = int(request.args.get("limit", 100))
    action_filter = request.args.get("action")
    user_filter = request.args.get("user_id")

    storage = get_storage()
    # Incident responders only see investigation-related logs if filtered
    if current_user and current_user.role == UserRole.INCIDENT_RESPONDER:
        logs = storage.get_audit_logs(limit=limit, user_id=current_user.id, action=action_filter)
    else:
        logs = storage.get_audit_logs(limit=limit, user_id=user_filter, action=action_filter)

    return jsonify([log.to_dict() for log in logs])
