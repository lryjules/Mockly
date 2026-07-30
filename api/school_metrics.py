"""
Indicateurs scopés à une école, pour le tableau de bord "profil école" :
KPIs du pool d'élèves, stats par élève, compétences les moins bien notées
sur l'ensemble du pool. Même logique de calcul qu'admin_metrics.py, mais
toujours filtrée sur users.school_id = l'école du compte connecté.
"""

import json

from api.db import get_db

ACTIVE_WINDOW_DAYS = 30


def _safe_div(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _pool_kpis(conn, school_id: str) -> dict:
    nb_students = conn.execute(
        "SELECT COUNT(*) FROM users WHERE school_id=? AND is_admin=0 AND is_school_admin=0",
        (school_id,)
    ).fetchone()[0]

    active_students = conn.execute(f"""
        SELECT COUNT(DISTINCT u.id) FROM users u
        WHERE u.school_id = ? AND (
            EXISTS (SELECT 1 FROM sessions s WHERE s.user_id = u.id AND s.created_at >= datetime('now', '-{ACTIVE_WINDOW_DAYS} days'))
            OR EXISTS (SELECT 1 FROM job_interviews ji WHERE ji.user_id = u.id AND ji.created_at >= datetime('now', '-{ACTIVE_WINDOW_DAYS} days'))
        )
    """, (school_id,)).fetchone()[0]

    interviews_started = conn.execute("""
        SELECT COUNT(*) FROM job_interviews ji
        JOIN users u ON u.id = ji.user_id
        WHERE u.school_id = ?
    """, (school_id,)).fetchone()[0]

    interviews_completed = conn.execute("""
        SELECT COUNT(*) FROM job_interviews ji
        JOIN users u ON u.id = ji.user_id
        WHERE u.school_id = ? AND ji.status = 'completed'
    """, (school_id,)).fetchone()[0]

    score_rows = conn.execute("""
        SELECT ji.final_evaluation FROM job_interviews ji
        JOIN users u ON u.id = ji.user_id
        WHERE u.school_id = ? AND ji.status = 'completed' AND ji.final_evaluation IS NOT NULL
    """, (school_id,)).fetchall()

    scores = []
    for row in score_rows:
        try:
            score = json.loads(row["final_evaluation"]).get("score_global")
        except (ValueError, TypeError):
            score = None
        if score is not None:
            scores.append(score)
    average_score = round(sum(scores) / len(scores), 1) if scores else None

    credits_row = conn.execute(
        "SELECT SUM(interview_credits) AS total_interview, SUM(coach_credits) AS total_coach "
        "FROM users WHERE school_id=? AND is_admin=0 AND is_school_admin=0",
        (school_id,)
    ).fetchone()

    return {
        "nb_students": nb_students,
        "active_students": active_students,
        "active_window_days": ACTIVE_WINDOW_DAYS,
        "interviews_started": interviews_started,
        "interviews_completed": interviews_completed,
        "completion_rate": _safe_div(interviews_completed, interviews_started),
        "average_score": average_score,
        "total_interview_credits": credits_row["total_interview"] or 0,
        "total_coach_credits": credits_row["total_coach"] or 0,
    }


def _student_list(conn, school_id: str) -> list[dict]:
    rows = conn.execute("""
        SELECT u.id, u.email, u.created_at, u.interview_credits, u.coach_credits,
               COUNT(DISTINCT s.id)  AS nb_sessions,
               COUNT(DISTINCT ji.id) AS nb_interviews
        FROM users u
        LEFT JOIN sessions s ON s.user_id = u.id
        LEFT JOIN job_interviews ji ON ji.user_id = u.id
        WHERE u.school_id = ? AND u.is_admin = 0 AND u.is_school_admin = 0
        GROUP BY u.id
        ORDER BY u.created_at DESC
    """, (school_id,)).fetchall()

    students = []
    for row in rows:
        score_rows = conn.execute("""
            SELECT final_evaluation FROM job_interviews
            WHERE user_id=? AND status='completed' AND final_evaluation IS NOT NULL
        """, (row["id"],)).fetchall()
        scores = []
        for r in score_rows:
            try:
                score = json.loads(r["final_evaluation"]).get("score_global")
            except (ValueError, TypeError):
                score = None
            if score is not None:
                scores.append(score)

        students.append({
            "id": row["id"],
            "email": row["email"],
            "created_at": row["created_at"],
            "nb_sessions": row["nb_sessions"],
            "nb_interviews": row["nb_interviews"],
            "interview_credits": row["interview_credits"],
            "coach_credits": row["coach_credits"],
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
        })
    return students


def _weakest_competencies(conn, school_id: str, limit: int = 10) -> dict:
    """Compétences les moins bien notées sur le pool — seulement celles réellement
    évaluées (evaluation_count > 0), jamais les branches "déclarées" non testées."""
    by_name = conn.execute("""
        SELECT sc.name, sc.category,
               AVG(sc.current_score) AS avg_score,
               COUNT(DISTINCT sc.student_id) AS nb_students
        FROM student_competency sc
        JOIN users u ON u.id = sc.student_id
        WHERE u.school_id = ? AND sc.evaluation_count > 0
        GROUP BY sc.name
        ORDER BY avg_score ASC
        LIMIT ?
    """, (school_id, limit)).fetchall()

    by_category = conn.execute("""
        SELECT sc.category,
               AVG(sc.current_score) AS avg_score,
               COUNT(DISTINCT sc.student_id) AS nb_students
        FROM student_competency sc
        JOIN users u ON u.id = sc.student_id
        WHERE u.school_id = ? AND sc.evaluation_count > 0
        GROUP BY sc.category
        ORDER BY avg_score ASC
    """, (school_id,)).fetchall()

    return {
        "by_name": [
            {"name": r["name"], "category": r["category"], "average_score": round(r["avg_score"], 1), "nb_students": r["nb_students"]}
            for r in by_name
        ],
        "by_category": [
            {"category": r["category"], "average_score": round(r["avg_score"], 1), "nb_students": r["nb_students"]}
            for r in by_category
        ],
    }


def get_school_dashboard(school_id: str) -> dict:
    with get_db() as conn:
        school = conn.execute("SELECT id, name FROM schools WHERE id=?", (school_id,)).fetchone()
        if not school:
            return None

        return {
            "school": {"id": school["id"], "name": school["name"]},
            "kpis": _pool_kpis(conn, school_id),
            "students": _student_list(conn, school_id),
            "weakest_competencies": _weakest_competencies(conn, school_id),
        }
