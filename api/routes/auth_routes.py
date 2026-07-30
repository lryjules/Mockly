"""Routes d'authentification : /api/signup, /api/login, /api/schools."""

import uuid

from flask import Blueprint, request, jsonify

from api.db import get_db
from api.user_helpers import hash_password, get_informations_pro

auth_bp = Blueprint("auth", __name__)


def _user_payload(row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "is_admin": bool(row["is_admin"]),
        "is_school_admin": bool(row["is_school_admin"]),
        "school_id": row["school_id"],
    }


@auth_bp.route("/api/schools", methods=["GET"])
def list_schools_public():
    """Public (pas d'auth) : alimente le menu déroulant "école" du formulaire d'inscription."""
    with get_db() as conn:
        rows = conn.execute("SELECT id, name FROM schools ORDER BY name").fetchall()
    return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])


@auth_bp.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    confirm_password = (data.get("confirmPassword") or "").strip()
    school_id = (data.get("school_id") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400
    if password != confirm_password:
        return jsonify({"error": "La confirmation du mot de passe ne correspond pas"}), 400
    if not school_id:
        return jsonify({"error": "Sélectionne ton école"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            return jsonify({"error": "Cet email est déjà utilisé"}), 409

        school = conn.execute("SELECT id FROM schools WHERE id=?", (school_id,)).fetchone()
        if not school:
            return jsonify({"error": "École inconnue"}), 400

        user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash, school_id) VALUES (?,?,?,?)",
            (user_id, email, hash_password(password), school_id)
        )
        conn.execute("INSERT INTO informations_pro (user_id) VALUES (?)", (user_id,))

    return jsonify({
        "message": "Compte créé",
        "user": {"id": user_id, "email": email, "is_admin": False, "is_school_admin": False, "school_id": school_id}
    })


@auth_bp.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400

    with get_db() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash, is_admin, is_school_admin, school_id FROM users WHERE email=?",
            (email,)
        ).fetchone()

    if not user or user["password_hash"] != hash_password(password):
        return jsonify({"error": "Identifiants invalides"}), 401

    profile = get_informations_pro(user["id"])
    return jsonify({
        "message": "Connexion réussie",
        "user": _user_payload(user),
        "profile": profile or {}
    })