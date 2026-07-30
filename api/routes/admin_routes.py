"""Routes du tableau de bord admin : /api/admin/kpis, /api/admin/business-metrics.

Sécurité : comme le reste de l'app, l'identité vient d'un user_id transmis
par le client (pas de session/JWT signée nulle part dans ce projet) — donc
tout comme /api/sessions ou /api/informations-pro, ce n'est robuste que
tant que l'UUID admin ne fuite pas. C'est cohérent avec le modèle d'auth
existant, mais ce n'est pas une isolation de niveau production.
"""

from flask import Blueprint, request, jsonify

from api.db import get_db
from api import admin_metrics

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
            SELECT u.id, u.email, u.is_admin, u.interview_credits, u.coach_credits, u.created_at,
                   COUNT(DISTINCT s.id)  AS nb_sessions,
                   COUNT(DISTINCT ji.id) AS nb_interviews
            FROM users u
            LEFT JOIN sessions s ON s.user_id = u.id
            LEFT JOIN job_interviews ji ON ji.user_id = u.id
            GROUP BY u.id
            ORDER BY u.created_at DESC
        """).fetchall()

    return jsonify([dict(row) for row in rows])


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
