"""Routes du tableau de bord "profil école" : /api/school/dashboard,
/api/school/students/<id>/credits, /api/school/credits/bulk.

Sécurité : l'identité vient d'un token de session Clerk vérifié (@require_auth,
voir api/clerk_auth.py). Chaque action est en plus scopée au school_id du
compte "profil école" qui appelle — un compte école ne peut jamais lire ni
modifier un élève d'une autre école.
"""

from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api import school_metrics
from api.security import limiter
from api.clerk_auth import require_auth, get_or_create_local_user

school_bp = Blueprint("school", __name__)

MAX_CREDITS = 10_000
MAX_CREDIT_DELTA = 10_000


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


@school_bp.route("/api/school/students/<student_id>/credits", methods=["POST"])
@require_auth
@limiter.limit("60 per hour")
def update_student_credits(student_id):
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403
    data = request.get_json(force=True)

    updates = {}
    for key in ("interview_credits", "coach_credits"):
        if key in data:
            try:
                updates[key] = max(0, min(MAX_CREDITS, int(data[key])))
            except (TypeError, ValueError):
                return jsonify({"error": f"{key} doit être un entier"}), 400

    if not updates:
        return jsonify({"error": "Aucun champ à mettre à jour"}), 400

    with get_db() as conn:
        student = conn.execute(
            "SELECT id FROM users WHERE id=%s AND school_id=%s", (student_id, admin["school_id"])
        ).fetchone()
        if not student:
            return jsonify({"error": "Élève introuvable dans ton école"}), 404

        set_clause = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE users SET {set_clause} WHERE id=%s", (*updates.values(), student_id))

        row = conn.execute(
            "SELECT interview_credits, coach_credits FROM users WHERE id=%s", (student_id,)
        ).fetchone()

    return jsonify({"interview_credits": row["interview_credits"], "coach_credits": row["coach_credits"]})


@school_bp.route("/api/school/credits/bulk", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def bulk_update_credits():
    """Ajoute (ou retire, avec un delta négatif) des crédits à tout le pool d'élèves de l'école."""
    admin = _get_school_admin(g.clerk_user_id)
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403
    data = request.get_json(force=True)

    deltas = {}
    for key in ("interview_credits", "coach_credits"):
        if key in data:
            try:
                deltas[key] = max(-MAX_CREDIT_DELTA, min(MAX_CREDIT_DELTA, int(data[key])))
            except (TypeError, ValueError):
                return jsonify({"error": f"{key} doit être un entier"}), 400

    if not deltas:
        return jsonify({"error": "Aucun champ à mettre à jour"}), 400

    with get_db() as conn:
        for key, delta in deltas.items():
            conn.execute(
                f"UPDATE users SET {key} = MIN({MAX_CREDITS}, MAX(0, {key} + %s)) "
                "WHERE school_id=%s AND is_admin=0 AND is_school_admin=0",
                (delta, admin["school_id"])
            )
        nb_students = conn.execute(
            "SELECT COUNT(*) FROM users WHERE school_id=%s AND is_admin=0 AND is_school_admin=0",
            (admin["school_id"],)
        ).fetchone()[0]

    return jsonify({"message": "Crédits mis à jour", "nb_students": nb_students})
