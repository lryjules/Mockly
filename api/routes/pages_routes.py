"""Sert le frontend statique : /, /results, /interview, /configuration, /profile,
/admin, /school, plus le catch-all qui sert le reste (CSS/JS) puisque app.py
désactive le static_folder automatique de Flask (static_folder=None)."""

from pathlib import Path

from flask import Blueprint, send_from_directory

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@pages_bp.route("/results")
def results_page():
    return send_from_directory(str(FRONTEND_DIR), "results.html")


@pages_bp.route("/interview")
def interview_page():
    return send_from_directory(str(FRONTEND_DIR), "interview.html")


@pages_bp.route("/configuration")
def configuration_page():
    return send_from_directory(str(FRONTEND_DIR), "configuration.html")


@pages_bp.route("/profile")
def profile_page():
    return send_from_directory(str(FRONTEND_DIR), "profile.html")


@pages_bp.route("/admin")
def admin_page():
    return send_from_directory(str(FRONTEND_DIR), "admin.html")


@pages_bp.route("/school")
def school_page():
    return send_from_directory(str(FRONTEND_DIR), "school.html")


# Catch-all : DOIT rester la dernière route enregistrée (voir app.py), sinon
# elle intercepterait les routes ci-dessus.
@pages_bp.route("/<path:path>")
def static_files(path):
    return send_from_directory(str(FRONTEND_DIR), path)
