"""
Calcule les indicateurs du tableau de bord admin à partir des données
réellement collectées par l'app (utilisateurs, sessions CV, entretiens audio,
journal d'appels IA). Rien n'est inventé : chaque métrique documente sa
formule dans son commentaire, pour rester vérifiable.

Les métriques "Business" et une partie des métriques "Pilot Success"
(satisfaction, coûts d'acquisition...) n'ont aucune source dans l'usage de
l'app — ce sont des données CRM/business externes — elles sont donc saisies
manuellement par l'admin et simplement relues ici (cf. business_metric).
"""

import json

from api.db import get_db
from api.ai_logging import estimate_cost

ACTIVE_WINDOW_DAYS = 30

BUSINESS_METRIC_KEYS = [
    "schools_contacted",
    "meetings",
    "demos",
    "pilot_proposals",
    "pilots_signed",
    "annual_contract_value",
    "customer_acquisition_cost",
    "gross_margin_pct",
    "satisfaction",
    "career_center_satisfaction",
]


def _safe_div(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _product_metrics(conn) -> dict:
    registered_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=0").fetchone()[0]

    # "Actif" = a créé au moins une session CV ou un entretien audio dans la
    # fenêtre glissante ACTIVE_WINDOW_DAYS.
    active_users = conn.execute(f"""
        SELECT COUNT(DISTINCT user_id) FROM (
            SELECT user_id FROM sessions
            WHERE user_id IS NOT NULL AND created_at::timestamp >= now() - interval '{ACTIVE_WINDOW_DAYS} days'
            UNION
            SELECT user_id FROM job_interviews
            WHERE user_id IS NOT NULL AND created_at::timestamp >= now() - interval '{ACTIVE_WINDOW_DAYS} days'
        ) AS t
    """).fetchone()[0]

    interviews_started = conn.execute("SELECT COUNT(*) FROM job_interviews").fetchone()[0]
    interviews_completed = conn.execute(
        "SELECT COUNT(*) FROM job_interviews WHERE status='completed'"
    ).fetchone()[0]

    # Répétition : parmi les utilisateurs ayant démarré >=1 entretien, la part
    # qui en a démarré plus d'un.
    interview_counts_per_user = conn.execute("""
        SELECT COUNT(*) as n FROM job_interviews
        WHERE user_id IS NOT NULL
        GROUP BY user_id
    """).fetchall()
    users_with_interview = len(interview_counts_per_user)
    users_with_repeat = sum(1 for row in interview_counts_per_user if row["n"] > 1)

    # Score moyen + progression : lus depuis final_evaluation (JSON) des
    # entretiens terminés, par utilisateur, triés chronologiquement.
    rows = conn.execute("""
        SELECT user_id, created_at, final_evaluation FROM job_interviews
        WHERE status='completed' AND final_evaluation IS NOT NULL AND user_id IS NOT NULL
        ORDER BY user_id, created_at
    """).fetchall()

    scores_by_user = {}
    all_scores = []
    for row in rows:
        try:
            evaluation = json.loads(row["final_evaluation"])
            score = evaluation.get("score_global")
        except (ValueError, TypeError):
            score = None
        if score is None:
            continue
        all_scores.append(score)
        scores_by_user.setdefault(row["user_id"], []).append(score)

    average_score = _safe_div(sum(all_scores), len(all_scores)) if all_scores else None

    progressions = [
        scores[-1] - scores[0]
        for scores in scores_by_user.values()
        if len(scores) >= 2
    ]
    score_progression = _safe_div(sum(progressions), len(progressions)) if progressions else None

    # Durée moyenne d'entretien (proxy de "durée de session" : aucune notion
    # générique de session avec début/fin n'existe ailleurs dans l'app).
    duration_row = conn.execute("""
        SELECT AVG(
            EXTRACT(EPOCH FROM (completed_at::timestamp - created_at::timestamp)) / 60
        ) AS avg_minutes
        FROM job_interviews
        WHERE status='completed' AND completed_at IS NOT NULL
    """).fetchone()
    average_session_duration_minutes = round(duration_row["avg_minutes"], 1) if duration_row["avg_minutes"] else None

    return {
        "registered_users": registered_users,
        "active_users": active_users,
        "active_window_days": ACTIVE_WINDOW_DAYS,
        "interviews_started": interviews_started,
        "interviews_completed": interviews_completed,
        "completion_rate": _safe_div(interviews_completed, interviews_started),
        "interviews_per_active_student": _safe_div(interviews_started, active_users),
        "repeat_usage_rate": _safe_div(users_with_repeat, users_with_interview),
        "average_score": average_score,
        "score_progression": score_progression,
        "average_session_duration_minutes": average_session_duration_minutes,
    }


def _ai_metrics(conn) -> dict:
    total_calls = conn.execute("SELECT COUNT(*) FROM ai_call_log").fetchone()[0]
    errors = conn.execute("SELECT COUNT(*) FROM ai_call_log WHERE success=0").fetchone()[0]

    agg = conn.execute("""
        SELECT AVG(latency_ms)::float AS avg_latency,
               SUM(input_tokens) AS total_input,
               SUM(output_tokens) AS total_output
        FROM ai_call_log
    """).fetchone()

    interview_agg = conn.execute("""
        SELECT SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens
        FROM ai_call_log
        WHERE interview_id IS NOT NULL
    """).fetchone()
    interviews_started = conn.execute("SELECT COUNT(*) FROM job_interviews").fetchone()[0]

    interview_input_tokens = interview_agg["input_tokens"] or 0
    interview_output_tokens = interview_agg["output_tokens"] or 0
    interview_cost = estimate_cost(interview_input_tokens, interview_output_tokens)
    total_cost = estimate_cost(agg["total_input"] or 0, agg["total_output"] or 0)

    model_rows = conn.execute("""
        SELECT model, COUNT(*) as n FROM ai_call_log
        WHERE model IS NOT NULL
        GROUP BY model
        ORDER BY n DESC
    """).fetchall()
    model_distribution = [
        {"model": row["model"], "count": row["n"], "share": _safe_div(row["n"], total_calls)}
        for row in model_rows
    ]

    return {
        "total_calls": total_calls,
        "cost_per_interview": round(_safe_div(interview_cost, interviews_started), 4),
        "input_tokens_per_interview": round(_safe_div(interview_input_tokens, interviews_started), 1),
        "output_tokens_per_interview": round(_safe_div(interview_output_tokens, interviews_started), 1),
        "average_latency_ms": round(agg["avg_latency"], 0) if agg["avg_latency"] else None,
        "error_rate": _safe_div(errors, total_calls),
        "model_distribution": model_distribution,
        "total_cost_usd": round(total_cost, 4),
    }


def _pilot_metrics(conn, product: dict, ai: dict, business: dict) -> dict:
    active_users = product["active_users"] or 0
    interviews_completed = product["interviews_completed"] or 0

    return {
        "student_activation_rate": _safe_div(active_users, product["registered_users"]),
        "student_completion_rate": product["completion_rate"],
        "repeat_practice_rate": product["repeat_usage_rate"],
        "satisfaction": business.get("satisfaction"),
        "career_center_satisfaction": business.get("career_center_satisfaction"),
        "cost_per_active_student": round(_safe_div(ai["total_cost_usd"], active_users), 4) if active_users else None,
        "cost_per_completed_interview": round(_safe_div(ai["total_cost_usd"], interviews_completed), 4) if interviews_completed else None,
    }


def get_business_metrics(conn) -> dict:
    rows = conn.execute("SELECT key, value FROM business_metric").fetchall()
    values = {row["key"]: row["value"] for row in rows}
    metrics = {key: values.get(key) for key in BUSINESS_METRIC_KEYS}
    metrics["pilot_conversion_rate"] = _safe_div(
        metrics.get("pilots_signed") or 0, metrics.get("pilot_proposals") or 0
    )
    return metrics


def get_all_kpis() -> dict:
    with get_db() as conn:
        product = _product_metrics(conn)
        ai = _ai_metrics(conn)
        business = get_business_metrics(conn)
        pilot = _pilot_metrics(conn, product, ai, business)

    return {
        "product": product,
        "ai": ai,
        "business": business,
        "pilot": pilot,
    }
