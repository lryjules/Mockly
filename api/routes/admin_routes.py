"""Routes du tableau de bord admin : /api/admin/kpis, /api/admin/business-metrics.

Sécurité : l'identité vient d'un token de session Clerk vérifié par
@require_auth (voir api/clerk_auth.py) — g.clerk_user_id est donc fiable.
Le statut admin lui-même reste une donnée locale (users.is_admin), promue par
email via CLERK_ADMIN_EMAILS.
"""

import uuid

from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api import admin_metrics
from api.security import limiter, validate_length
from api.clerk_auth import require_auth, get_or_create_local_user

admin_bp = Blueprint("admin", __name__)

MAX_SCHOOL_NAME_LEN = 120
MAX_EMAIL_LEN = 254
MAX_CREDITS = 10_000


def _is_admin(clerk_user_id: str | None) -> bool:
    if not clerk_user_id:
        return False
    row = get_or_create_local_user(clerk_user_id)
    return bool(row and row["is_admin"])


@admin_bp.route("/api/admin/kpis", methods=["GET"])
@require_auth
def get_kpis():
    if not _is_admin(g.clerk_user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    return jsonify(admin_metrics.get_all_kpis())


@admin_bp.route("/api/admin/business-metrics", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def save_business_metrics():
    if not _is_admin(g.clerk_user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403
    data = request.get_json(force=True)

    metrics = data.get("metrics") or {}
    valid_keys = set(admin_metrics.BUSINESS_METRIC_KEYS)

    with get_db() as conn:
        for key, value in metrics.items():
            if key not in valid_keys:
                continue
            if value is None or value == "":
                conn.execute("DELETE FROM business_metric WHERE key=%s", (key,))
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            conn.execute(
                """INSERT INTO business_metric (key, value, updated_at) VALUES (%s, %s, to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, numeric_value)
            )

    with get_db() as conn:
        business = admin_metrics.get_business_metrics(conn)
    return jsonify({"business": business})


@admin_bp.route("/api/admin/users", methods=["GET"])
@require_auth
def list_users():
    if not _is_admin(g.clerk_user_id):
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
            GROUP BY u.id, sc.name
            ORDER BY u.created_at DESC
        """).fetchall()

    return jsonify([dict(row) for row in rows])


@admin_bp.route("/api/admin/schools", methods=["GET"])
@require_auth
def list_schools():
    if not _is_admin(g.clerk_user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    with get_db() as conn:
        rows = conn.execute("""
            SELECT sc.id, sc.name, sc.created_at,
                   COUNT(DISTINCT u.id) FILTER (WHERE u.is_admin = 0 AND u.is_school_admin = 0) AS nb_students,
                   admin_u.id    AS admin_id,
                   admin_u.email AS admin_email,
                   inv.email     AS pending_admin_email
            FROM schools sc
            LEFT JOIN users u ON u.school_id = sc.id
            LEFT JOIN users admin_u ON admin_u.school_id = sc.id AND admin_u.is_school_admin = 1
            LEFT JOIN school_admin_invites inv ON inv.school_id = sc.id
            GROUP BY sc.id, admin_u.id, admin_u.email, inv.email
            ORDER BY sc.name
        """).fetchall()

    return jsonify([dict(row) for row in rows])


@admin_bp.route("/api/admin/schools", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def create_school():
    """Crée une école et désigne son compte de gestion par email.

    Avec Clerk, on ne crée plus de mot de passe local : si `admin_email` a déjà
    un compte Clerk (donc une ligne locale déjà provisionnée), la promotion
    is_school_admin/school_id est appliquée immédiatement ; sinon elle est mise
    en attente (school_admin_invites) et appliquée à son premier login Clerk
    (voir api/clerk_auth.py::_apply_pending_school_invite)."""
    data = request.get_json(force=True)
    if not _is_admin(g.clerk_user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    name = (data.get("name") or "").strip()
    admin_email = (data.get("admin_email") or "").strip().lower()

    if not name:
        return jsonify({"error": "Nom de l'école requis"}), 400
    if not admin_email:
        return jsonify({"error": "Email du compte école requis"}), 400
    if err := validate_length(name, "Nom de l'école", MAX_SCHOOL_NAME_LEN):
        return err
    if err := validate_length(admin_email, "Email", MAX_EMAIL_LEN):
        return err

    with get_db() as conn:
        existing_school = conn.execute("SELECT id FROM schools WHERE name=%s", (name,)).fetchone()
        if existing_school:
            return jsonify({"error": "Une école avec ce nom existe déjà"}), 409

        school_id = str(uuid.uuid4())
        conn.execute("INSERT INTO schools (id, name) VALUES (%s, %s)", (school_id, name))

        existing_user = conn.execute("SELECT id FROM users WHERE email=%s", (admin_email,)).fetchone()
        if existing_user:
            conn.execute(
                "UPDATE users SET is_school_admin=1, school_id=%s WHERE id=%s",
                (school_id, existing_user["id"])
            )
            status = "applied"
        else:
            conn.execute(
                "INSERT INTO school_admin_invites (email, school_id) VALUES (%s, %s)",
                (admin_email, school_id)
            )
            status = "pending"

    return jsonify({
        "message": "École créée",
        "school": {"id": school_id, "name": name},
        "admin_invite": {"email": admin_email, "status": status}
    })


@admin_bp.route("/api/admin/schools/<school_id>", methods=["DELETE"])
@require_auth
@limiter.limit("20 per hour")
def delete_school(school_id):
    if not _is_admin(g.clerk_user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403

    with get_db() as conn:
        nb_linked = conn.execute(
            "SELECT COUNT(*) FROM users WHERE school_id=%s AND is_school_admin=0", (school_id,)
        ).fetchone()[0]
        if nb_linked:
            return jsonify({"error": "Impossible : des étudiants sont encore rattachés à cette école"}), 409

        conn.execute("DELETE FROM users WHERE school_id=%s AND is_school_admin=1", (school_id,))
        conn.execute("DELETE FROM school_admin_invites WHERE school_id=%s", (school_id,))
        deleted = conn.execute("DELETE FROM schools WHERE id=%s", (school_id,))

    if deleted.rowcount == 0:
        return jsonify({"error": "École introuvable"}), 404

    return jsonify({"message": "École supprimée"})


@admin_bp.route("/api/admin/users/<target_user_id>/credits", methods=["POST"])
@require_auth
@limiter.limit("60 per hour")
def update_user_credits(target_user_id):
    if not _is_admin(g.clerk_user_id):
        return jsonify({"error": "Accès réservé aux administrateurs"}), 403
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
        existing = conn.execute("SELECT id FROM users WHERE id=%s", (target_user_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Utilisateur introuvable"}), 404

        set_clause = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE users SET {set_clause} WHERE id=%s", (*updates.values(), target_user_id))

        row = conn.execute(
            "SELECT interview_credits, coach_credits FROM users WHERE id=%s", (target_user_id,)
        ).fetchone()

    return jsonify({"interview_credits": row["interview_credits"], "coach_credits": row["coach_credits"]})
