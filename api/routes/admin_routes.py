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
