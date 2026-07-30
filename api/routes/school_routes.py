"""Routes du tableau de bord "profil école" : /api/school/dashboard,
/api/school/students/<id>/credits, /api/school/credits/bulk.

Sécurité : même modèle que le reste de l'app (user_id transmis par le
client, pas de session signée). Chaque action est en plus scopée au
school_id du compte "profil école" qui appelle — un compte école ne peut
jamais lire ni modifier un élève d'une autre école.
"""

from flask import Blueprint, request, jsonify

from api.db import get_db
from api import school_metrics

school_bp = Blueprint("school", __name__)


def _get_school_admin(user_id: str | None):
    """Renvoie la ligne users si user_id est un compte "profil école" valide, sinon None."""
    if not user_id:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, school_id, is_school_admin FROM users WHERE id=?", (user_id,)
        ).fetchone()
    if not row or not row["is_school_admin"] or not row["school_id"]:
        return None
    return row


@school_bp.route("/api/school/dashboard", methods=["GET"])
def get_dashboard():
    admin = _get_school_admin(request.args.get("user_id"))
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403

    dashboard = school_metrics.get_school_dashboard(admin["school_id"])
    return jsonify(dashboard)


@school_bp.route("/api/school/students/<student_id>/credits", methods=["POST"])
def update_student_credits(student_id):
    data = request.get_json(force=True)
    admin = _get_school_admin(data.get("user_id"))
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403

    updates = {}
    for key in ("interview_credits", "coach_credits"):
        if key in data:
            try:
                updates[key] = max(0, int(data[key]))
            except (TypeError, ValueError):
                return jsonify({"error": f"{key} doit être un entier"}), 400

    if not updates:
        return jsonify({"error": "Aucun champ à mettre à jour"}), 400

    with get_db() as conn:
        student = conn.execute(
            "SELECT id FROM users WHERE id=? AND school_id=?", (student_id, admin["school_id"])
        ).fetchone()
        if not student:
            return jsonify({"error": "Élève introuvable dans ton école"}), 404

        set_clause = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", (*updates.values(), student_id))

        row = conn.execute(
            "SELECT interview_credits, coach_credits FROM users WHERE id=?", (student_id,)
        ).fetchone()

    return jsonify({"interview_credits": row["interview_credits"], "coach_credits": row["coach_credits"]})


@school_bp.route("/api/school/credits/bulk", methods=["POST"])
def bulk_update_credits():
    """Ajoute (ou retire, avec un delta négatif) des crédits à tout le pool d'élèves de l'école."""
    data = request.get_json(force=True)
    admin = _get_school_admin(data.get("user_id"))
    if not admin:
        return jsonify({"error": "Accès réservé aux comptes école"}), 403

    deltas = {}
    for key in ("interview_credits", "coach_credits"):
        if key in data:
            try:
                deltas[key] = int(data[key])
            except (TypeError, ValueError):
                return jsonify({"error": f"{key} doit être un entier"}), 400

    if not deltas:
        return jsonify({"error": "Aucun champ à mettre à jour"}), 400

    with get_db() as conn:
        for key, delta in deltas.items():
            conn.execute(
                f"UPDATE users SET {key} = MAX(0, {key} + ?) "
                "WHERE school_id=? AND is_admin=0 AND is_school_admin=0",
                (delta, admin["school_id"])
            )
        nb_students = conn.execute(
            "SELECT COUNT(*) FROM users WHERE school_id=? AND is_admin=0 AND is_school_admin=0",
            (admin["school_id"],)
        ).fetchone()[0]

    return jsonify({"message": "Crédits mis à jour", "nb_students": nb_students})
