"""Routes d'identité : /api/config, /api/schools, /api/me, /api/me/school.

L'authentification elle-même (mot de passe, session) est déléguée à Clerk —
ce blueprint ne fait plus que : exposer la clé publique Clerk au front,
lister les écoles (pour l'onboarding post-inscription), et exposer/compléter
le profil local (rôle, crédits, école) une fois l'identité Clerk vérifiée.
Voir api/clerk_auth.py pour la vérification de token.
"""

from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api.user_helpers import get_informations_pro
from api.security import limiter, validate_length
from api.clerk_auth import require_auth, get_or_create_local_user, CLERK_PUBLISHABLE_KEY
from api import organizations

auth_bp = Blueprint("auth", __name__)

MAX_SCHOOL_ID_LEN = 100


def _user_payload(row: dict) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "is_admin": bool(row["is_admin"]),
        "is_school_admin": bool(row["is_school_admin"]),
        "school_id": row["school_id"],
    }


@auth_bp.route("/api/config", methods=["GET"])
def get_config():
    """Public : le front a besoin de la clé publishable pour initialiser le SDK Clerk."""
    return jsonify({"clerk_publishable_key": CLERK_PUBLISHABLE_KEY})


@auth_bp.route("/api/schools", methods=["GET"])
def list_schools_public():
    """Public (pas d'auth) : alimente le sélecteur d'école affiché après l'inscription Clerk."""
    with get_db() as conn:
        rows = conn.execute("SELECT id, name FROM schools ORDER BY name").fetchall()
    return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])


@auth_bp.route("/api/me", methods=["GET"])
@require_auth
def get_me():
    """Identité + profil de l'utilisateur Clerk actuellement connecté. Provisionne
    sa ligne locale (crédits par défaut, rôle) au tout premier appel."""
    row = get_or_create_local_user(g.clerk_user_id)
    profile = get_informations_pro(g.clerk_user_id)
    return jsonify({"user": _user_payload(row), "profile": profile or {}})


@auth_bp.route("/api/me/school", methods=["POST"])
@require_auth
@limiter.limit("10 per hour")
def set_my_school():
    """Complète l'inscription : Clerk ne connaît pas notre notion d'école, donc
    un compte fraîchement créé doit choisir la sienne ici avant d'accéder au
    workspace (voir onboarding.js côté front)."""
    data = request.get_json(force=True)
    school_id = (data.get("school_id") or "").strip()
    if err := validate_length(school_id, "school_id", MAX_SCHOOL_ID_LEN):
        return err
    if not school_id:
        return jsonify({"error": "Sélectionne ton école"}), 400

    get_or_create_local_user(g.clerk_user_id)

    with get_db() as conn:
        school = conn.execute("SELECT id FROM schools WHERE id=%s", (school_id,)).fetchone()
        if not school:
            return jsonify({"error": "École inconnue"}), 400
        conn.execute("UPDATE users SET school_id=%s WHERE id=%s", (school_id, g.clerk_user_id))
        organizations.upsert_membership(school_id, g.clerk_user_id, "STUDENT", conn=conn)
        row = conn.execute("SELECT * FROM users WHERE id=%s", (g.clerk_user_id,)).fetchone()

    return jsonify({"user": _user_payload(dict(row))})
