"""Authentication API Blueprint for TraceWise AO-03.
"""

from flask import Blueprint, jsonify, request
from app.storage import get_storage
from app.models.user import UserRole
from app.models.audit import AuditAction
from app.auth.session import login_user, logout_user, get_current_user
from app.auth.audit import log_audit_event
from app.auth.permissions import PERMISSION_MATRIX

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticates user with username & password, returns user object without secrets."""
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password:
        return jsonify({"error": "Username and password are required.", "code": "BAD_REQUEST"}), 400

    storage = get_storage()
    user = storage.get_user_by_username(username)

    if not user:
        log_audit_event(
            action=AuditAction.FAILED_LOGIN,
            resource_type="AUTH",
            result="FAILURE",
            metadata={"username": username, "reason": "User not found"},
        )
        return jsonify({"error": "Invalid username or password.", "code": "UNAUTHORIZED"}), 401

    if not user.is_active:
        log_audit_event(
            action=AuditAction.FAILED_LOGIN,
            resource_type="AUTH",
            resource_id=user.id,
            result="DENIED",
            metadata={"username": username, "reason": "Account disabled"},
            user=user,
        )
        return jsonify({"error": "Account is disabled. Please contact an administrator.", "code": "FORBIDDEN"}), 403

    if not user.check_password(password):
        log_audit_event(
            action=AuditAction.FAILED_LOGIN,
            resource_type="AUTH",
            resource_id=user.id,
            result="FAILURE",
            metadata={"username": username, "reason": "Password mismatch"},
            user=user,
        )
        return jsonify({"error": "Invalid username or password.", "code": "UNAUTHORIZED"}), 401

    # Login successful
    login_user(user)
    log_audit_event(
        action=AuditAction.LOGIN,
        resource_type="AUTH",
        resource_id=user.id,
        result="SUCCESS",
        metadata={"username": user.username, "role": user.role},
        user=user,
    )

    return jsonify({
        "status": "SUCCESS",
        "message": f"Welcome, {user.username}.",
        "user": user.to_dict(),
        "permissions": PERMISSION_MATRIX.get(user.role, {}),
    })


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Logs out current user and invalidates session."""
    user = get_current_user()
    if user:
        log_audit_event(
            action=AuditAction.LOGOUT,
            resource_type="AUTH",
            resource_id=user.id,
            result="SUCCESS",
            metadata={"username": user.username},
            user=user,
        )
    logout_user()
    resp = jsonify({"status": "SUCCESS", "message": "Logged out successfully."})
    resp.delete_cookie("session", path="/")
    return resp


@auth_bp.route("/me", methods=["GET"])
def me():
    """Returns current user's profile and active permissions."""
    user = get_current_user()
    if not user:
        return jsonify({
            "authenticated": False,
            "user": None,
            "permissions": None,
        })

    return jsonify({
        "authenticated": True,
        "user": user.to_dict(),
        "permissions": PERMISSION_MATRIX.get(user.role, {}),
    })


@auth_bp.route("/roles", methods=["GET"])
def list_roles():
    """Returns RBAC roles list and static permission matrix."""
    return jsonify({
        "roles": UserRole.ALL_ROLES,
        "permission_matrix": PERMISSION_MATRIX,
    })


@auth_bp.route("/demo-login", methods=["POST"])
def demo_login():
    """Allows one-click role switching for local hackathon demo/evaluators without exposing credentials."""
    data = request.get_json(silent=True) or {}
    raw_role = data.get("role", "")
    if raw_role:
        if raw_role.upper() not in ("ADMIN", "INCIDENT_RESPONDER", "SRE", "RESPONDER", "VIEWER", "AUDITOR"):
            return jsonify({"error": f"Invalid demo role '{raw_role}'.", "code": "INVALID_ROLE"}), 400
        requested_role = UserRole.normalize(raw_role)
    else:
        requested_role = UserRole.ADMIN

    storage = get_storage()
    users = storage.get_all_users()
    matched = next((u for u in users if u.role == requested_role and u.is_active), None)

    if not matched:
        return jsonify({"error": f"No active user found for role {requested_role}.", "code": "NOT_FOUND"}), 404

    login_user(matched)
    log_audit_event(
        action=AuditAction.LOGIN,
        resource_type="AUTH",
        resource_id=matched.id,
        result="SUCCESS",
        metadata={"username": matched.username, "role": matched.role, "demo_switch": True},
        user=matched,
    )
    return jsonify({
        "status": "SUCCESS",
        "message": f"Demo signed in as {matched.username} ({matched.role}).",
        "user": matched.to_dict(),
        "permissions": PERMISSION_MATRIX.get(matched.role, {}),
    })
