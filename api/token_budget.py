"""
Quota de tokens IA quotidien par étudiant, pour garder la main sur les coûts
IA sans le vocabulaire opaque des "crédits" :

- Chaque compte dispose d'un quota gratuit de DEFAULT_DAILY_TOKEN_LIMIT
  tokens/jour, partagé entre Coach et Interview (reset chaque jour à minuit,
  simplement parce qu'on regarde la date du jour — aucun job de reset requis).
- Une école peut relever ce quota pour certains élèves individuellement
  (users.bonus_daily_token_limit), dans la limite de son pool mensuel de
  bonus (schools.monthly_bonus_token_pool) : le bonus n'est décompté du pool
  qu'au moment où il est RÉELLEMENT consommé (au-delà du quota gratuit), pas
  au moment où l'école l'attribue — attribuer un gros bonus à un élève qui ne
  s'en sert jamais ne coûte rien au pool.
- Une fois le pool mensuel de l'école épuisé, tous ses élèves retombent sur
  le quota gratuit jusqu'au 1er du mois suivant, quel que soit le
  bonus_daily_token_limit individuel configuré.

L'usage réel (tokens effectivement consommés par les appels Gemini) est
enregistré par record_usage(), appelé depuis api.ai_logging.log_call — ce
module ne fait que lire ce compteur pour décider si une nouvelle requête IA
est autorisée.
"""

import datetime

from api.db import get_db

# Ordres de grandeur (tarif Gemini Flash ~$0.075/M tokens input, $0.30/M
# output — cf. api/ai_logging.py) : 50k tokens/jour couvre largement un
# entretien audio complet + une session de coach, pour un coût de l'ordre du
# centime par élève actif et par jour.
DEFAULT_DAILY_TOKEN_LIMIT = 50_000
MAX_DAILY_TOKEN_LIMIT = 300_000

DEFAULT_SCHOOL_MONTHLY_BONUS_POOL = 1_000_000
MAX_SCHOOL_MONTHLY_BONUS_POOL = 20_000_000


def _today() -> str:
    return datetime.date.today().isoformat()


def today() -> str:
    """Date du jour (YYYY-MM-DD), pour les requêtes admin/école qui doivent
    joindre token_usage_daily sur la journée en cours."""
    return _today()


def _this_month() -> str:
    return datetime.date.today().strftime("%Y-%m")


def this_month() -> str:
    """Mois courant (YYYY-MM), pour les affichages admin/école du pool mensuel."""
    return _this_month()


def _reset_school_pool_if_new_month(conn, school_id: str) -> None:
    month = _this_month()
    conn.execute(
        "UPDATE schools SET monthly_bonus_tokens_used=0, monthly_bonus_reset_month=%s "
        "WHERE id=%s AND monthly_bonus_reset_month <> %s",
        (month, school_id, month)
    )


def get_usage_today(conn, user_id: str) -> int:
    row = conn.execute(
        "SELECT tokens_used FROM token_usage_daily WHERE user_id=%s AND usage_date=%s",
        (user_id, _today())
    ).fetchone()
    return row["tokens_used"] if row else 0


def get_effective_daily_limit(conn, user_id: str) -> dict:
    """Renvoie {limit, base, bonus_active, bonus_configured, school_pool_exhausted}."""
    user = conn.execute(
        "SELECT school_id, bonus_daily_token_limit FROM users WHERE id=%s", (user_id,)
    ).fetchone()
    if not user:
        return {
            "limit": DEFAULT_DAILY_TOKEN_LIMIT, "base": DEFAULT_DAILY_TOKEN_LIMIT,
            "bonus_active": 0, "bonus_configured": 0, "school_pool_exhausted": False,
        }

    bonus_configured = user["bonus_daily_token_limit"] or 0
    bonus_active = 0
    pool_exhausted = False
    if bonus_configured > 0 and user["school_id"]:
        _reset_school_pool_if_new_month(conn, user["school_id"])
        school = conn.execute(
            "SELECT monthly_bonus_token_pool, monthly_bonus_tokens_used FROM schools WHERE id=%s",
            (user["school_id"],)
        ).fetchone()
        if school and school["monthly_bonus_tokens_used"] < school["monthly_bonus_token_pool"]:
            bonus_active = bonus_configured
        elif school:
            pool_exhausted = True

    limit = min(DEFAULT_DAILY_TOKEN_LIMIT + bonus_active, MAX_DAILY_TOKEN_LIMIT)
    return {
        "limit": limit, "base": DEFAULT_DAILY_TOKEN_LIMIT,
        "bonus_active": bonus_active, "bonus_configured": bonus_configured,
        "school_pool_exhausted": pool_exhausted,
    }


def has_budget(user_id: str) -> bool:
    with get_db() as conn:
        usage = get_usage_today(conn, user_id)
        info = get_effective_daily_limit(conn, user_id)
    return usage < info["limit"]


def get_status(user_id: str) -> dict:
    """Pour affichage (dashboard école/admin, futur badge côté étudiant)."""
    with get_db() as conn:
        usage = get_usage_today(conn, user_id)
        info = get_effective_daily_limit(conn, user_id)
    return {
        "used_today": usage,
        "limit_today": info["limit"],
        "remaining_today": max(0, info["limit"] - usage),
        "bonus_active": info["bonus_active"],
        "bonus_configured": info["bonus_configured"],
        "school_pool_exhausted": info["school_pool_exhausted"],
    }


def record_usage(conn, user_id: str, input_tokens: int | None, output_tokens: int | None) -> None:
    """Enregistre les tokens réellement consommés par un appel IA, et impute
    au pool mensuel de l'école la part au-delà du quota gratuit. Appelé
    depuis la même connexion/transaction que api.ai_logging.log_call — ne
    doit jamais lever (la journalisation ne doit jamais faire échouer
    l'appel IA lui-même)."""
    total = (input_tokens or 0) + (output_tokens or 0)
    if total <= 0 or not user_id:
        return

    try:
        user = conn.execute("SELECT school_id FROM users WHERE id=%s", (user_id,)).fetchone()
        if not user:
            return

        today = _today()
        prev_row = conn.execute(
            "SELECT tokens_used FROM token_usage_daily WHERE user_id=%s AND usage_date=%s",
            (user_id, today)
        ).fetchone()
        prev_total = prev_row["tokens_used"] if prev_row else 0

        conn.execute(
            """INSERT INTO token_usage_daily (user_id, usage_date, tokens_used)
               VALUES (%s,%s,%s)
               ON CONFLICT (user_id, usage_date)
               DO UPDATE SET tokens_used = token_usage_daily.tokens_used + excluded.tokens_used""",
            (user_id, today, total)
        )

        if user["school_id"]:
            new_total = prev_total + total
            overflow = max(0, new_total - DEFAULT_DAILY_TOKEN_LIMIT) - max(0, prev_total - DEFAULT_DAILY_TOKEN_LIMIT)
            if overflow > 0:
                _reset_school_pool_if_new_month(conn, user["school_id"])
                conn.execute(
                    "UPDATE schools SET monthly_bonus_tokens_used = monthly_bonus_tokens_used + %s WHERE id=%s",
                    (overflow, user["school_id"])
                )
    except Exception as e:
        print(f"[token_budget] Impossible d'enregistrer l'usage : {e}")
