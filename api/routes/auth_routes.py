"""Routes d'authentification : /api/signup, /api/login."""

import uuid

from flask import Blueprint, request, jsonify

from api.db import get_db
from api.user_helpers import hash_password, get_informations_pro

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    confirm_password = (data.get("confirmPassword") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400
    if password != confirm_password:
        return jsonify({"error": "La confirmation du mot de passe ne correspond pas"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            return jsonify({"error": "Cet email est déjà utilisé"}), 409

        user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash) VALUES (?,?,?)",
            (user_id, email, hash_password(password))
        )
        conn.execute("INSERT INTO informations_pro (user_id) VALUES (?)", (user_id,))

    return jsonify({"message": "Compte créé", "user": {"id": user_id, "email": email, "is_admin": False}})


@auth_bp.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400

    with get_db() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash, is_admin FROM users WHERE email=?",
            (email,)
        ).fetchone()

    if not user or user["password_hash"] != hash_password(password):
        return jsonify({"error": "Identifiants invalides"}), 401

    profile = get_informations_pro(user["id"])
    return jsonify({
        "message": "Connexion réussie",
        "user": {"id": user["id"], "email": user["email"], "is_admin": bool(user["is_admin"])},
        "profile": profile or {}
    })