"""
Moteur de profil étudiant : gère l'arbre de compétences socle, sa mise à
jour au fil des entretiens et du coach chat, le "seeding" de compétences
déclarées (CV) non encore confirmées, et le score de préparation par offre.

Distinction clé dans le modèle de données :
- declared=True, evaluation_count=0  → compétence mentionnée sur le CV/chat,
  jamais évaluée réellement. Affichée "grisée" côté front.
- evaluation_count>0                  → au moins une performance réelle jugée
  (entretien audio ou réponse notée en chat). current_score est fiable.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "interview_coach.db"

RECENCY_WEIGHT = 0.4
DEFAULT_NEUTRAL_SCORE = 50.0


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_tables() -> None:
    """Crée les tables du profil si elles n'existent pas. À appeler depuis app.py:init_db()."""
    with _get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS student_competency (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'autre',
                current_score REAL NOT NULL DEFAULT 0,
                evaluation_count INTEGER NOT NULL DEFAULT 0,
                declared INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(student_id, name)
            );

            CREATE TABLE IF NOT EXISTS competency_evaluation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_competency_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                score REAL NOT NULL,
                feedback TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_competency_id) REFERENCES student_competency(id)
            );
        """)
        # Migration douce si la table existait déjà sans la colonne 'declared'
        try:
            conn.execute("ALTER TABLE student_competency ADD COLUMN declared INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_competency(student_id: str, name: str) -> sqlite3.Row | None:
    with _get_connection() as conn:
        return conn.execute(
            "SELECT * FROM student_competency WHERE student_id = ? AND name = ?",
            (student_id, name),
        ).fetchone()


def get_all_competencies(student_id: str, evaluated_only: bool = False) -> list[sqlite3.Row]:
    with _get_connection() as conn:
        if evaluated_only:
            return conn.execute(
                "SELECT * FROM student_competency WHERE student_id = ? AND evaluation_count > 0",
                (student_id,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM student_competency WHERE student_id = ?",
            (student_id,),
        ).fetchall()


def get_or_create_competency(student_id: str, name: str, category: str = "autre",
                               declared: bool = False) -> sqlite3.Row:
    """Renvoie la compétence existante, ou la crée.

    declared=True ne s'applique qu'à la création : si la compétence existe déjà
    (même juste déclarée), on ne l'écrase pas ici — seule update_profile_tree
    modifie current_score/evaluation_count suite à une vraie évaluation.
    """
    existing = get_competency(student_id, name)
    if existing:
        return existing

    with _get_connection() as conn:
        conn.execute(
            """INSERT INTO student_competency
               (student_id, name, category, current_score, evaluation_count, declared, updated_at)
               VALUES (?, ?, ?, 0, 0, ?, ?)""",
            (student_id, name, category, int(declared), _now()),
        )
    return get_competency(student_id, name)


def seed_declared_competencies(student_id: str, names: list[str],
                                 category_map: dict[str, str] | None = None) -> None:
    """Ajoute des compétences "déclarées" (CV, chat libre) à l'arbre, sans score.

    N'écrase jamais une compétence déjà connue (déclarée ou déjà évaluée) :
    sert uniquement à peupler l'arbre pour les compétences jamais rencontrées.
    """
    category_map = category_map or {}
    cleaned_names = {n.strip() for n in names if n and n.strip()}
    for name in cleaned_names:
        get_or_create_competency(student_id, name, category_map.get(name, "autre"), declared=True)


def save_evaluation_history(student_competency_id: int, session_id: str, score: float, feedback: str = "") -> None:
    with _get_connection() as conn:
        conn.execute(
            """INSERT INTO competency_evaluation (student_competency_id, session_id, score, feedback, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (student_competency_id, session_id, score, feedback, _now()),
        )


def get_student_average_score(student_id: str) -> float:
    """Moyenne des scores actuels sur les compétences RÉELLEMENT évaluées (declared exclu)."""
    evaluated = get_all_competencies(student_id, evaluated_only=True)
    if not evaluated:
        return DEFAULT_NEUTRAL_SCORE
    return sum(row["current_score"] for row in evaluated) / len(evaluated)


def update_profile_tree(student_id: str, session_id: str,
                          competency_scores: dict[str, float],
                          category_map: dict[str, str] | None = None,
                          feedback_map: dict[str, str] | None = None) -> None:
    """Met à jour l'arbre socle suite à une VRAIE évaluation (entretien audio ou chat noté).

    Moyenne pondérée avec poids sur la récence (RECENCY_WEIGHT). Une compétence
    qui n'existait que "déclarée" (declared=True, evaluation_count=0) bascule
    naturellement en "confirmée" dès son premier evaluation_count > 0.
    """
    category_map = category_map or {}
    feedback_map = feedback_map or {}

    for name, new_score in competency_scores.items():
        category = category_map.get(name, "autre")
        comp = get_or_create_competency(student_id, name, category)

        if comp["evaluation_count"] == 0:
            updated_score = new_score
        else:
            updated_score = comp["current_score"] * (1 - RECENCY_WEIGHT) + new_score * RECENCY_WEIGHT

        with _get_connection() as conn:
            conn.execute(
                """UPDATE student_competency
                   SET current_score = ?, evaluation_count = evaluation_count + 1,
                       category = ?, updated_at = ?
                   WHERE id = ?""",
                (updated_score, category, _now(), comp["id"]),
            )

        save_evaluation_history(comp["id"], session_id, new_score, feedback_map.get(name, ""))


def compute_readiness_score(student_id: str, competencies: list[dict]) -> dict:
    """Score de préparation global pour une offre, pondéré par le caractère discriminant.

    Une compétence jamais évaluée reçoit comme score neutre la moyenne
    personnelle de l'étudiant (basée uniquement sur ses évaluations réelles).
    """
    if not competencies:
        return {"readiness_score": 0.0, "coverage": 0.0}

    neutral_score = get_student_average_score(student_id)

    total_weighted_score = 0.0
    total_weight = 0.0
    evaluated_count = 0

    for comp in competencies:
        name = comp["name"]
        weight = comp.get("weight", 2)
        student_comp = get_competency(student_id, name)

        if student_comp and student_comp["evaluation_count"] > 0:
            score = student_comp["current_score"]
            evaluated_count += 1
        else:
            score = neutral_score

        total_weighted_score += score * weight
        total_weight += weight

    readiness_score = round(total_weighted_score / total_weight, 1) if total_weight else 0.0
    coverage = round(evaluated_count / len(competencies), 2)

    return {"readiness_score": readiness_score, "coverage": coverage}


def get_competency_tree(student_id: str) -> dict:
    """Renvoie l'arbre de compétences complet, groupé par catégorie, pour l'affichage front.

    Chaque compétence inclut "confirmed" (evaluation_count > 0) : le front doit
    griser la branche quand confirmed=False (compétence déclarée mais jamais testée).
    """
    rows = get_all_competencies(student_id)
    tree: dict[str, list[dict]] = {"technique": [], "métier": [], "soft_skill": [], "autre": []}

    for row in rows:
        category = row["category"] if row["category"] in tree else "autre"
        tree[category].append({
            "name": row["name"],
            "current_score": round(row["current_score"], 1),
            "evaluation_count": row["evaluation_count"],
            "declared": bool(row["declared"]),
            "confirmed": row["evaluation_count"] > 0,
        })

    for category in tree:
        tree[category].sort(key=lambda c: (-c["confirmed"], -c["current_score"]))

    return tree


def finalize_interview_session(student_id: str, session_id: str,
                                 evaluation: dict, competency_metadata: dict[str, dict]) -> None:
    """À appeler depuis app.py juste après interviewengine.generate_final_evaluation().

    evaluation          : dict renvoyé par generate_final_evaluation()
                          ("par_competence": [{competence, score /10, commentaire}])
    competency_metadata : {"SQL": {"category": "technique", "weight": 3}, ...}
    """
    competency_scores = {}
    category_map = {}
    feedback_map = {}

    for item in evaluation.get("par_competence", []):
        name = item.get("competence")
        score_sur_10 = item.get("score")
        if name and score_sur_10 is not None:
            competency_scores[name] = score_sur_10 * 10
            category_map[name] = competency_metadata.get(name, {}).get("category", "autre")
            feedback_map[name] = item.get("commentaire", "")

    if competency_scores:
        update_profile_tree(student_id, session_id, competency_scores, category_map, feedback_map)