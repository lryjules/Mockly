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
from api import token_budget
from api import organizations
from api.security import limiter, validate_length
from api.clerk_auth import require_auth, require_super_admin

admin_bp = Blueprint("admin", __name__)

MAX_SCHOOL_NAME_LEN = 120
MAX_EMAIL_LEN = 254
MAX_BONUS_DAILY_TOKENS = token_budget.MAX_DAILY_TOKEN_LIMIT - token_budget.DEFAULT_DAILY_TOKEN_LIMIT


@admin_bp.route("/api/admin/kpis", methods=["GET"])
@require_auth
@require_super_admin
def get_kpis():
    return jsonify(admin_metrics.get_all_kpis())


@admin_bp.route("/api/admin/business-metrics", methods=["POST"])
@require_auth
@require_super_admin
@limiter.limit("30 per hour")
def save_business_metrics():
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
@require_super_admin
def list_users():
    today = token_budget.today()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT u.id, u.email, u.is_admin, u.is_school_admin, u.school_id, sc.name AS school_name,
                   u.bonus_daily_token_limit, u.created_at,
                   COALESCE(t.tokens_used, 0) AS tokens_used_today,
                   COUNT(DISTINCT s.id)  AS nb_sessions,
                   COUNT(DISTINCT ji.id) AS nb_interviews
            FROM users u
            LEFT JOIN schools sc ON sc.id = u.school_id
            LEFT JOIN sessions s ON s.user_id = u.id
            LEFT JOIN job_interviews ji ON ji.user_id = u.id
            LEFT JOIN token_usage_daily t ON t.user_id = u.id AND t.usage_date = %s
            GROUP BY u.id, sc.name, t.tokens_used
            ORDER BY u.created_at DESC
        """, (today,)).fetchall()

    users = []
    for row in rows:
        d = dict(row)
        d["daily_token_limit"] = token_budget.DEFAULT_DAILY_TOKEN_LIMIT + (row["bonus_daily_token_limit"] or 0)
        users.append(d)
    return jsonify(users)


@admin_bp.route("/api/admin/schools", methods=["GET"])
@require_auth
@require_super_admin
def list_schools():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT sc.id, sc.name, sc.created_at,
                   sc.monthly_bonus_token_pool, sc.monthly_bonus_tokens_used, sc.monthly_bonus_reset_month,
                   COUNT(DISTINCT u.id) FILTER (WHERE u.is_admin = 0 AND u.is_school_admin = 0) AS nb_students,
                   admin_u.id    AS admin_id,
                   admin_u.email AS admin_email,
                   inv.email     AS pending_admin_email,
                   sub.status               AS subscription_status,
                   sub.student_limit        AS student_limit,
                   sub.current_period_end   AS current_period_end
            FROM schools sc
            LEFT JOIN users u ON u.school_id = sc.id
            LEFT JOIN users admin_u ON admin_u.school_id = sc.id AND admin_u.is_school_admin = 1
            LEFT JOIN pending_org_invites inv ON inv.organization_id = sc.id AND inv.role = 'SCHOOL_ADMIN'
            LEFT JOIN subscriptions sub ON sub.organization_id = sc.id
            GROUP BY sc.id, admin_u.id, admin_u.email, inv.email, sub.status, sub.student_limit, sub.current_period_end
            ORDER BY sc.name
        """).fetchall()

    current_month = token_budget.this_month()
    schools = []
    for row in rows:
        d = dict(row)
        if d["monthly_bonus_reset_month"] != current_month:
            d["monthly_bonus_tokens_used"] = 0
        schools.append(d)
    return jsonify(schools)


@admin_bp.route("/api/admin/schools", methods=["POST"])
@require_auth
@require_super_admin
@limiter.limit("20 per hour")
def create_school():
    """Crée une école et désigne son compte de gestion par email.

    Avec Clerk, on ne crée plus de mot de passe local : si `admin_email` a déjà
    un compte Clerk (donc une ligne locale déjà provisionnée), la promotion
    is_school_admin/school_id est appliquée immédiatement ; sinon elle est mise
    en attente (pending_org_invites) et appliquée à son premier login Clerk
    (voir api/clerk_auth.py::_apply_pending_org_invite)."""
    data = request.get_json(force=True)

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
        organizations.get_or_create_subscription(school_id, conn=conn)

        result = organizations.send_org_invite(
            admin_email, school_id, "SCHOOL_ADMIN", invited_by=g.clerk_user_id, conn=conn
        )
        status = result["status"]

    return jsonify({
        "message": "École créée",
        "school": {"id": school_id, "name": name},
        "admin_invite": {"email": admin_email, "status": status}
    })


@admin_bp.route("/api/admin/schools/<school_id>", methods=["DELETE"])
@require_auth
@require_super_admin
@limiter.limit("20 per hour")
def delete_school(school_id):
    with get_db() as conn:
        nb_linked = conn.execute(
            "SELECT COUNT(*) FROM users WHERE school_id=%s AND is_school_admin=0", (school_id,)
        ).fetchone()[0]
        if nb_linked:
            return jsonify({"error": "Impossible : des étudiants sont encore rattachés à cette école"}), 409

        conn.execute("DELETE FROM users WHERE school_id=%s AND is_school_admin=1", (school_id,))
        conn.execute("DELETE FROM pending_org_invites WHERE organization_id=%s", (school_id,))
        conn.execute("DELETE FROM organization_members WHERE organization_id=%s", (school_id,))
        conn.execute("DELETE FROM subscriptions WHERE organization_id=%s", (school_id,))
        deleted = conn.execute("DELETE FROM schools WHERE id=%s", (school_id,))

    if deleted.rowcount == 0:
        return jsonify({"error": "École introuvable"}), 404

    return jsonify({"message": "École supprimée"})


@admin_bp.route("/api/admin/users/<target_user_id>/token-bonus", methods=["POST"])
@require_auth
@require_super_admin
@limiter.limit("60 per hour")
def update_user_token_bonus(target_user_id):
    """Ajuste le bonus quotidien de tokens (au-delà du quota gratuit de
    token_budget.DEFAULT_DAILY_TOKEN_LIMIT) d'un utilisateur. Contrairement à
    l'école (voir school_routes.py), l'admin plateforme n'est pas contraint
    par un pool mensuel : c'est lui qui définit le pool de chaque école."""
    data = request.get_json(force=True)

    if "bonus_daily_token_limit" not in data:
        return jsonify({"error": "bonus_daily_token_limit requis"}), 400
    try:
        bonus = max(0, min(MAX_BONUS_DAILY_TOKENS, int(data["bonus_daily_token_limit"])))
    except (TypeError, ValueError):
        return jsonify({"error": "bonus_daily_token_limit doit être un entier"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE id=%s", (target_user_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Utilisateur introuvable"}), 404

        conn.execute("UPDATE users SET bonus_daily_token_limit=%s WHERE id=%s", (bonus, target_user_id))

    return jsonify({
        "bonus_daily_token_limit": bonus,
        "daily_token_limit": token_budget.DEFAULT_DAILY_TOKEN_LIMIT + bonus,
    })


@admin_bp.route("/api/admin/schools/<school_id>/token-pool", methods=["POST"])
@require_auth
@require_super_admin
@limiter.limit("60 per hour")
def update_school_token_pool(school_id):
    """Définit le pool mensuel de tokens bonus qu'une école peut distribuer à
    ses élèves — c'est le levier de facturation/plan de l'admin plateforme."""
    data = request.get_json(force=True)

    if "monthly_bonus_token_pool" not in data:
        return jsonify({"error": "monthly_bonus_token_pool requis"}), 400
    try:
        pool = max(0, min(token_budget.MAX_SCHOOL_MONTHLY_BONUS_POOL, int(data["monthly_bonus_token_pool"])))
    except (TypeError, ValueError):
        return jsonify({"error": "monthly_bonus_token_pool doit être un entier"}), 400

    with get_db() as conn:
        updated = conn.execute(
            "UPDATE schools SET monthly_bonus_token_pool=%s WHERE id=%s", (pool, school_id)
        )
    if updated.rowcount == 0:
        return jsonify({"error": "École introuvable"}), 404

    return jsonify({"monthly_bonus_token_pool": pool})
