"""Services and Topology API endpoints for AO-03.
"""

from flask import Blueprint, jsonify
from app.storage import get_storage
from app.engine.dependency_graph import DependencyGraphManager
from app.auth.decorators import login_required

topology_bp = Blueprint("topology", __name__, url_prefix="/api")


@topology_bp.route("/services", methods=["GET"])
@login_required
def list_services():
    storage = get_storage()
    services = storage.get_services()
    return jsonify([s.to_dict() for s in services])


@topology_bp.route("/dependencies", methods=["GET"])
@login_required
def list_dependencies():
    storage = get_storage()
    dependencies = storage.get_dependencies()
    return jsonify([d.to_dict() for d in dependencies])


@topology_bp.route("/topology", methods=["GET"])
@login_required
def get_topology():
    storage = get_storage()
    services = storage.get_services()
    dependencies = storage.get_dependencies()
    graph_manager = DependencyGraphManager(services, dependencies)

    nodes = [
        {
            "id": s.id,
            "label": s.name,
            "tier": s.tier,
            "description": s.description,
        }
        for s in services
    ]

    edges = [
        {
            "id": f"{d.source_service}->{d.target_service}",
            "source": d.source_service,
            "target": d.target_service,
            "call_type": d.call_type,
            "critical": d.critical,
        }
        for d in dependencies
    ]

    return jsonify({"nodes": nodes, "edges": edges})
