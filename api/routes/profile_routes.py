"""Routes de profil : informations pro, readiness-check, arbre de compétences.

Toutes ces routes agissent sur le profil de l'utilisateur Clerk authentifié
(g.clerk_user_id) — jamais sur un user_id arbitraire passé par le client."""

from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api.user_helpers import get_informations_pro
from api import profileprocessing
from api import profile_engine
from api.security import limiter, validate_length
from api.clerk_auth import require_auth, get_or_create_local_user

profile_bp = Blueprint("profile", __name__)

MAX_PROFILE_FIELD_LEN = 300
MAX_JOB_DESCRIPTION_LEN = 6000


@profile_bp.route("/api/informations-pro", methods=["GET"])
@require_auth
def get_informations_pro_route():
    get_or_create_local_user(g.clerk_user_id)
    profile = get_informations_pro(g.clerk_user_id)
    return jsonify({"profile": profile or {}})


@profile_bp.route("/api/informations-pro", methods=["POST"])
@require_auth
def save_informations_pro():
    data = request.get_json(force=True)
    study_level = (data.get("studyLevel") or "").strip()
    target_domain = (data.get("targetDomain") or "").strip()
    current_goal = (data.get("currentGoal") or "").strip()

    for field_name, field_value in (
        ("studyLevel", study_level), ("targetDomain", target_domain), ("currentGoal", current_goal)
    ):
        if err := validate_length(field_value, field_name, MAX_PROFILE_FIELD_LEN):
            return err

    user_id = g.clerk_user_id
    get_or_create_local_user(user_id)

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM informations_pro WHERE user_id=%s", (user_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE informations_pro SET study_level=%s, target_domain=%s, current_goal=%s, updated_at=to_char(now(), 'YYYY-MM-DD HH24:MI:SS') WHERE user_id=%s",
                (study_level, target_domain, current_goal, user_id)
            )
        else:
            conn.execute(
                "INSERT INTO informations_pro (user_id, study_level, target_domain, current_goal) VALUES (%s,%s,%s,%s)",
                (user_id, study_level, target_domain, current_goal)
            )

    return jsonify({"message": "Informations enregistrées", "profile": {
        "study_level": study_level,
        "target_domain": target_domain,
        "current_goal": current_goal,
    }})


@profile_bp.route("/api/profile/readiness-check", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def readiness_check():
    """Preview du score de préparation avant de lancer un entretien audio complet."""
    data = request.get_json(force=True)
    job_description = (data.get("job_description") or "").strip()

    if not job_description:
        return jsonify({"error": "job_description requis"}), 400
    if err := validate_length(job_description, "job_description", MAX_JOB_DESCRIPTION_LEN):
        return err

    get_or_create_local_user(g.clerk_user_id)
    analysis = profileprocessing.analyze_job_posting(job_description)
    readiness = profile_engine.compute_readiness_score(g.clerk_user_id, analysis["competencies"])

    return jsonify({
        "job_title": analysis["job_title"],
        "competencies": analysis["competencies"],
        **readiness,
    })


@profile_bp.route("/api/profile/competencies", methods=["GET"])
@require_auth
def get_profile_competencies():
    """Arbre de compétences complet, groupé par catégorie, pour la page 'Ma progression'.

    Les compétences "hard skill" (technique/métier) confirmées reçoivent en
    plus un classement anonyme au sein de l'école de l'étudiant (rank/total
    sur les autres élèves ayant aussi cette compétence évaluée) — voir
    profile_engine.get_skill_rankings."""
    user = get_or_create_local_user(g.clerk_user_id)
    tree = profile_engine.get_competency_tree(g.clerk_user_id)

    rankings = profile_engine.get_skill_rankings(g.clerk_user_id, user.get("school_id"))
    for category in profile_engine.RANKING_CATEGORIES:
        for comp in tree.get(category, []):
            ranking = rankings.get(comp["name"])
            if ranking:
                comp["school_rank"] = ranking["rank"]
                comp["school_rank_total"] = ranking["total"]

    return jsonify(tree)


@profile_bp.route("/api/profile/priority-skills", methods=["GET"])
@require_auth
def get_priority_skills_route():
    """3 compétences clés à travailler en priorité pour l'objectif de carrière
    déclaré (informations_pro.target_domain/current_goal) — voir
    profile_engine.get_priority_skills. Aucun appel IA : matching ESCO local."""
    get_or_create_local_user(g.clerk_user_id)
    infos = get_informations_pro(g.clerk_user_id) or {}
    result = profile_engine.get_priority_skills(
        g.clerk_user_id, infos.get("target_domain", ""), infos.get("current_goal", "")
    )
    return jsonify(result)
