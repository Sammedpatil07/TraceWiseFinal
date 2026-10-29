"""Flask Application Factory for AO-03.
"""

from flask import Flask, render_template, send_from_directory
from app.config import Config
from app.storage import get_storage
from app.api import incidents_bp, evidence_bp, topology_bp, demo_bp, auth_bp, admin_bp


def create_app(config_class=Config) -> Flask:
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    app.config.from_object(config_class)

    # Initialize storage tables
    storage = get_storage()
    storage.init_db()

    # Register API blueprints
    app.register_blueprint(incidents_bp)
    app.register_blueprint(evidence_bp)
    app.register_blueprint(topology_bp)
    app.register_blueprint(demo_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    # Main Dashboard Route
    @app.route("/")
    def index():
        return render_template("index.html")

    return app
