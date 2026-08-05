"""
Crédits par compte qui gouvernent l'accès aux fonctionnalités qui appellent
Gemini, pour que l'admin garde la main sur les coûts IA :

- coach_credits     : 1 crédit consommé par dépôt de CV (déverrouille le chat
                       coach, la génération de carte mentale et les
                       évaluations de réponses, sans coût supplémentaire,
                       pour cette session).
- interview_credits : 1 crédit consommé par entretien audio démarré.

Par défaut chaque compte a 3 crédits de chaque (colonnes users.*_credits,
DEFAULT 3). L'admin peut les ajuster depuis le tableau de bord.
"""

from api.db import get_db

CREDIT_COLUMNS = {"interview": "interview_credits", "coach": "coach_credits"}


def get_credits(user_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT interview_credits, coach_credits FROM users WHERE id=%s", (user_id,)
        ).fetchone()
    if not row:
        return None
    return {"interview_credits": row["interview_credits"], "coach_credits": row["coach_credits"]}


def has_credit(user_id: str, kind: str) -> bool:
    """kind : 'interview' ou 'coach'."""
    credits = get_credits(user_id)
    if credits is None:
        return False
    column = CREDIT_COLUMNS[kind]
    return credits[column] > 0


def consume_credit(user_id: str, kind: str) -> bool:
    """Décrémente le crédit si disponible (opération atomique). Renvoie False
    si l'utilisateur n'existe pas ou n'a plus de crédit — dans ce cas rien
    n'est décrémenté."""
    column = CREDIT_COLUMNS[kind]
    with get_db() as conn:
        cursor = conn.execute(
            f"UPDATE users SET {column} = {column} - 1 WHERE id=%s AND {column} > 0",
            (user_id,)
        )
        return cursor.rowcount > 0
