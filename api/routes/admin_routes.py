"""Routes du tableau de bord admin : /api/admin/kpis, /api/admin/business-metrics.

Sécurité : comme le reste de l'app, l'identité vient d'un user_id transmis
par le client (pas de session/JWT signée nulle part dans ce projet) — donc
tout comme /api/sessions ou /api/informations-pro, ce n'est robuste que
tant que l'UUID admin ne fuite pas. C'est cohérent avec le modèle d'auth
existant, mais ce n'est pas une isolation de niveau production.
"""

import uuid

from flask import Blueprint, request, jsonify

from api.db import get_db
from api import admin_metrics
from api.user_helpers import hash_password

admin_bp = Blueprint("admin", __name__)


def _is_admin(user_id: str | None) -> bool:
    if not user_id:
        return False
    with get_db() as conn:
        row = conn.execute("SELECT is_admin FROM users WHERE id=?", (user_id,)).fetchone()
    return bool(row and row["is_admin"])


@admin_bp.route("/api/admin/kpis", methods=["GET"])
def get_kpis():
    user_id = request.args.get("user_id")
    if not _is_admin(user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    return jsonify(admin_metrics.get_all_kpis())


@admin_bp.route("/api/admin/business-metrics", methods=["POST"])
def save_business_metrics():
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    if not _is_admin(user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    metrics = data.get("metrics") or {}
    valid_keys = set(admin_metrics.BUSINESS_METRIC_KEYS)

    with get_db() as conn:
        for key, value in metrics.items():
            if key not in valid_keys:
                continue
            if value is None or value == "":
                conn.execute("DELETE FROM business_metric WHERE key=?", (key,))
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            conn.execute(
                """INSERT INTO business_metric (key, value, updated_at) VALUES (?, ?, datetime('now'))
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, numeric_value)
            )

    with get_db() as conn:
        business = admin_metrics.get_business_metrics(conn)
    return jsonify({"business": business})


@admin_bp.route("/api/admin/users", methods=["GET"])
def list_users():
    user_id = request.args.get("user_id")
    if not _is_admin(user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    with get_db() as conn:
        rows = conn.execute("""
            SELECT u.id, u.email, u.is_admin, u.is_school_admin, u.school_id, sc.name AS school_name,
                   u.interview_credits, u.coach_credits, u.created_at,
                   COUNT(DISTINCT s.id)  AS nb_sessions,
                   COUNT(DISTINCT ji.id) AS nb_interviews
            FROM users u
            LEFT JOIN schools sc ON sc.id = u.school_id
            LEFT JOIN sessions s ON s.user_id = u.id
            LEFT JOIN job_interviews ji ON ji.user_id = u.id
            GROUP BY u.id
            ORDER BY u.created_at DESC
        """).fetchall()

    return jsonify([dict(row) for row in rows])


@admin_bp.route("/api/admin/schools", methods=["GET"])
def list_schools():
    user_id = request.args.get("user_id")
    if not _is_admin(user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    with get_db() as conn:
        rows = conn.execute("""
            SELECT sc.id, sc.name, sc.created_at,
                   COUNT(DISTINCT u.id) FILTER (WHERE u.is_admin = 0 AND u.is_school_admin = 0) AS nb_students,
                   admin_u.id    AS admin_id,
                   admin_u.email AS admin_email
            FROM schools sc
            LEFT JOIN users u ON u.school_id = sc.id
            LEFT JOIN users admin_u ON admin_u.school_id = sc.id AND admin_u.is_school_admin = 1
            GROUP BY sc.id
            ORDER BY sc.name
        """).fetchall()

    return jsonify([dict(row) for row in rows])


@admin_bp.route("/api/admin/schools", methods=["POST"])
def create_school():
    """Crée une école + son compte de gestion associé (is_school_admin=1) en une seule action."""
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    if not _is_admin(user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    name = (data.get("name") or "").strip()
    admin_email = (data.get("admin_email") or "").strip().lower()
    admin_password = (data.get("admin_password") or "").strip()

    if not name:
        return jsonify({"error": "Nom de l'école requis"}), 400
    if not admin_email or not admin_password:
        return jsonify({"error": "Email et mot de passe du compte école requis"}), 400

    with get_db() as conn:
        existing_school = conn.execute("SELECT id FROM schools WHERE name=?", (name,)).fetchone()
        if existing_school:
            return jsonify({"error": "Une école avec ce nom existe déjà"}), 409

        existing_user = conn.execute("SELECT id FROM users WHERE email=?", (admin_email,)).fetchone()
        if existing_user:
            return jsonify({"error": "Cet email est déjà utilisé"}), 409

        school_id = str(uuid.uuid4())
        conn.execute("INSERT INTO schools (id, name) VALUES (?, ?)", (school_id, name))

        school_admin_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash, school_id, is_school_admin) VALUES (?,?,?,?,1)",
            (school_admin_id, admin_email, hash_password(admin_password), school_id)
        )

    return jsonify({
        "message": "École créée",
        "school": {"id": school_id, "name": name},
        "admin_account": {"id": school_admin_id, "email": admin_email}
    })


@admin_bp.route("/api/admin/schools/<school_id>", methods=["DELETE"])
def delete_school(school_id):
    user_id = request.args.get("user_id")
    if not _is_admin(user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    with get_db() as conn:
        nb_linked = conn.execute(
            "SELECT COUNT(*) FROM users WHERE school_id=? AND is_school_admin=0", (school_id,)
        ).fetchone()[0]
        if nb_linked:
            return jsonify({"error": "Impossible : des étudiants sont encore rattachés à cette école"}), 409

        conn.execute("DELETE FROM users WHERE school_id=? AND is_school_admin=1", (school_id,))
        deleted = conn.execute("DELETE FROM schools WHERE id=?", (school_id,))

    if deleted.rowcount == 0:
        return jsonify({"error": "École introuvable"}), 404

    return jsonify({"message": "École supprimée"})


@admin_bp.route("/api/admin/users/<target_user_id>/credits", methods=["POST"])
def update_user_credits(target_user_id):
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    if not _is_admin(user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

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
        existing = conn.execute("SELECT id FROM users WHERE id=?", (target_user_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Utilisateur introuvable"}), 404

        set_clause = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", (*updates.values(), target_user_id))

        row = conn.execute(
            "SELECT interview_credits, coach_credits FROM users WHERE id=?", (target_user_id,)
        ).fetchone()

    return jsonify({"interview_credits": row["interview_credits"], "coach_credits": row["coach_credits"]})
