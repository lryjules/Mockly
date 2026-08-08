"""Routes du tableau de bord "profil école" : /api/school/dashboard,
/api/school/students/<id>/token-bonus, /api/school/token-bonus/bulk.

Sécurité : l'identité vient d'un token de session Clerk vérifié (@require_auth,
voir api/clerk_auth.py). Chaque action est en plus scopée au school_id du
compte "profil école" qui appelle — un compte école ne peut jamais lire ni
modifier un élève d'une autre école.

Le bonus quotidien accordé à un élève (au-delà du quota gratuit défini par
api.token_budget.DEFAULT_DAILY_TOKEN_LIMIT) n'est jamais garanti au moment où
il est réglé ici : il n'est réellement actif que tant que le pool mensuel de
l'école (schools.monthly_bonus_token_pool) n'est pas épuisé — voir
api/token_budget.py::get_effective_daily_limit.
"""

from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api import school_metrics
from api import token_budget
from api.security import limiter
from api.clerk_auth import require_auth, get_or_create_local_user

school_bp = Blueprint("school", __name__)

MAX_BONUS_DAILY_TOKENS = token_budget.MAX_DAILY_TOKEN_LIMIT - token_budget.DEFAULT_DAILY_TOKEN_LIMIT


def _get_school_admin(clerk_user_id: str | None):
    """Renvoie le profil local si cet utilisateur Clerk est un compte "profil école" valide, sinon None."""
    if not clerk_user_id:
        return None
    row = get_or_create_local_user(clerk_user_id)
    if not row or not row["is_school_admin"] or not row["school_id"]:
        return None
    return row


@school_bp.route("/api/school/dashboard", methods=["GET"])
@require_auth
def get_dashboard():
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403

    dashboard = school_metrics.get_school_dashboard(admin["school_id"])
    return jsonify(dashboard)


@school_bp.route("/api/school/students/<student_id>/token-bonus", methods=["POST"])
@require_auth
@limiter.limit("60 per hour")
def update_student_token_bonus(student_id):
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403
    data = request.get_json(force=True)

    if "bonus_daily_token_limit" not in data:
        return jsonify({"error": "bonus_daily_token_limit requis"}), 400
    try:
        bonus = max(0, min(MAX_BONUS_DAILY_TOKENS, int(data["bonus_daily_token_limit"])))
    except (TypeError, ValueError):
        return jsonify({"error": "bonus_daily_token_limit doit être un entier"}), 400

    with get_db() as conn:
        student = conn.execute(
            "SELECT id FROM users WHERE id=%s AND school_id=%s", (student_id, admin["school_id"])
        ).fetchone()
        if not student:
            return jsonify({"error": "Élève introuvable dans ton école"}), 404

        conn.execute("UPDATE users SET bonus_daily_token_limit=%s WHERE id=%s", (bonus, student_id))

    return jsonify({
        "bonus_daily_token_limit": bonus,
        "daily_token_limit": token_budget.DEFAULT_DAILY_TOKEN_LIMIT + bonus,
    })


@school_bp.route("/api/school/token-bonus/bulk", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def bulk_update_token_bonus():
    """Ajoute (ou retire, avec un delta négatif) un bonus quotidien à tout le pool d'élèves de l'école."""
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403
    data = request.get_json(force=True)

    if "bonus_daily_token_limit_delta" not in data:
        return jsonify({"error": "bonus_daily_token_limit_delta requis"}), 400
    try:
        delta = max(-MAX_BONUS_DAILY_TOKENS, min(MAX_BONUS_DAILY_TOKENS, int(data["bonus_daily_token_limit_delta"])))
    except (TypeError, ValueError):
        return jsonify({"error": "bonus_daily_token_limit_delta doit être un entier"}), 400

    with get_db() as conn:
        conn.execute(
            f"UPDATE users SET bonus_daily_token_limit = LEAST({MAX_BONUS_DAILY_TOKENS}, GREATEST(0, bonus_daily_token_limit + %s)) "
            "WHERE school_id=%s AND is_admin=0 AND is_school_admin=0",
            (delta, admin["school_id"])
        )
        nb_students = conn.execute(
            "SELECT COUNT(*) FROM users WHERE school_id=%s AND is_admin=0 AND is_school_admin=0",
            (admin["school_id"],)
        ).fetchone()[0]

    return jsonify({"message": "Bonus de tokens mis à jour", "nb_students": nb_students})
