"""Routes de profil : informations pro, readiness-check, arbre de compétences."""

from flask import Blueprint, request, jsonify

from api.db import get_db
from api.user_helpers import get_informations_pro
from api import profileprocessing
from api import profile_engine

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/api/informations-pro/<user_id>", methods=["GET"])
def get_informations_pro_route(user_id):
    profile = get_informations_pro(user_id)
    if profile is None:
        return jsonify({"error": "Profil introuvable"}), 404
    return jsonify({"profile": profile})


@profile_bp.route("/api/informations-pro", methods=["POST"])
def save_informations_pro():
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    study_level = (data.get("studyLevel") or "").strip()
    target_domain = (data.get("targetDomain") or "").strip()
    current_goal = (data.get("currentGoal") or "").strip()

    if not user_id:
        return jsonify({"error": "user_id requis"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM informations_pro WHERE user_id=?", (user_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE informations_pro SET study_level=?, target_domain=?, current_goal=?, updated_at=datetime('now') WHERE user_id=?",
                (study_level, target_domain, current_goal, user_id)
            )
        else:
            conn.execute(
                "INSERT INTO informations_pro (user_id, study_level, target_domain, current_goal) VALUES (?,?,?,?)",
                (user_id, study_level, target_domain, current_goal)
            )

    return jsonify({"message": "Informations enregistrées", "profile": {
        "study_level": study_level,
        "target_domain": target_domain,
        "current_goal": current_goal,
    }})


@profile_bp.route("/api/profile/readiness-check", methods=["POST"])
def readiness_check():
    """Preview du score de préparation avant de lancer un entretien audio complet."""
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    job_description = (data.get("job_description") or "").strip()

    if not user_id or not job_description:
        return jsonify({"error": "user_id et job_description requis"}), 400

    analysis = profileprocessing.analyze_job_posting(job_description)
    readiness = profile_engine.compute_readiness_score(user_id, analysis["competencies"])

    return jsonify({
        "job_title": analysis["job_title"],
        "competencies": analysis["competencies"],
        **readiness,
    })


@profile_bp.route("/api/profile/competencies/<user_id>", methods=["GET"])
def get_profile_competencies(user_id):
    """Arbre de compétences complet, groupé par catégorie, pour la page 'Ma progression'."""
    return jsonify(profile_engine.get_competency_tree(user_id))