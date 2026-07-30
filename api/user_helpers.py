"""
Helpers partagés autour de l'utilisateur : hash de mot de passe et lecture
des informations professionnelles (utilisés par auth_routes, chat_routes,
topics_routes...).
"""

import hashlib

from api.db import get_db


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_informations_pro(user_id: str | None) -> dict | None:
    if not user_id:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT study_level, target_domain, current_goal FROM informations_pro WHERE user_id=?",
            (user_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "study_level": row["study_level"],
        "target_domain": row["target_domain"],
        "current_goal": row["current_goal"],
    }


def get_informations_pro_for_session(session_id: str | None) -> dict | None:
    if not session_id:
        return None
    with get_db() as conn:
        row = conn.execute("SELECT user_id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not row or not row["user_id"]:
        return None
    return get_informations_pro(row["user_id"])