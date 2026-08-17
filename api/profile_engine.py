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

from datetime import datetime, timezone

from api.db import get_db
from api import esco_engine

RECENCY_WEIGHT = 0.4
DEFAULT_NEUTRAL_SCORE = 50.0

# "Hard skills" (au sens de ce classement) = compétences techniques ou métier,
# à l'exclusion des soft skills — un classement de "empathie" ou "communication"
# entre élèves n'a pas de sens, contrairement à "Python" ou "Finance".
RANKING_CATEGORIES = ("technique", "métier")
# En dessous, l'échantillon est trop petit pour être parlant (un élève seul
# sur une compétence de niche se verrait "1er sur 1") : on n'affiche rien.
MIN_STUDENTS_FOR_RANKING = 5

# get_priority_skills : une compétence essentielle du métier visé est jugée
# "faible" (donc éligible aux 3 compétences clés) en dessous de ce score.
# Aligné sur DEFAULT_NEUTRAL_SCORE, déjà utilisé plus bas comme référence
# neutre — sous la moyenne neutre, on considère que ça vaut la peine de
# travailler cette compétence en priorité.
LOW_SCORE_THRESHOLD = 50.0
MAX_PRIORITY_SKILLS = 3

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS student_competency (
        id SERIAL PRIMARY KEY,
        student_id TEXT NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'autre',
        current_score REAL NOT NULL DEFAULT 0,
        evaluation_count INTEGER NOT NULL DEFAULT 0,
        declared INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        UNIQUE(student_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS competency_evaluation (
        id SERIAL PRIMARY KEY,
        student_competency_id INTEGER NOT NULL REFERENCES student_competency(id),
        session_id TEXT NOT NULL,
        score REAL NOT NULL,
        feedback TEXT,
        created_at TEXT NOT NULL
    )
    """,
]


def init_tables() -> None:
    """Crée les tables du profil si elles n'existent pas. À appeler depuis api/db.py:init_db()."""
    with get_db() as conn:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        # Migration douce si la table existait déjà sans la colonne 'declared'.
        conn.execute("ALTER TABLE student_competency ADD COLUMN IF NOT EXISTS declared INTEGER NOT NULL DEFAULT 0")
        # esco_uri : rattachement (interne, jamais affiché) à un skill ESCO — sert
        # à dédupliquer les libellés proches et au gap-analysis de get_priority_skills.
        # Nullable : les lignes existantes restent NULL jusqu'à leur prochaine
        # écriture (backfill paresseux, voir seed_declared_competencies).
        conn.execute("ALTER TABLE student_competency ADD COLUMN IF NOT EXISTS esco_uri TEXT")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_competency(student_id: str, name: str, conn=None) -> dict | None:
    """Si `conn` est fourni, l'utilise directement (pas de nouvelle connexion
    Postgres) — indispensable pour les appelants qui bouclent sur plusieurs
    compétences (voir seed_declared_competencies/update_profile_tree/
    compute_readiness_score), qui ouvraient sinon une connexion par nom."""
    if conn is not None:
        return conn.execute(
            "SELECT * FROM student_competency WHERE student_id = %s AND name = %s",
            (student_id, name),
        ).fetchone()
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM student_competency WHERE student_id = %s AND name = %s",
            (student_id, name),
        ).fetchone()


def get_all_competencies(student_id: str, evaluated_only: bool = False) -> list[dict]:
    with get_db() as conn:
        if evaluated_only:
            return conn.execute(
                "SELECT * FROM student_competency WHERE student_id = %s AND evaluation_count > 0",
                (student_id,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM student_competency WHERE student_id = %s",
            (student_id,),
        ).fetchall()


def get_or_create_competency(student_id: str, name: str, category: str = "autre",
                               declared: bool = False, esco_uri: str | None = None,
                               conn=None) -> dict:
    """Renvoie la compétence existante, ou la crée.

    declared=True ne s'applique qu'à la création : si la compétence existe déjà
    (même juste déclarée), on ne l'écrase pas ici — seule update_profile_tree
    modifie current_score/evaluation_count suite à une vraie évaluation.

    esco_uri (calculé par l'appelant via esco_engine.match_skill, jamais ici —
    ce module ne dépend pas d'esco_engine) : métadonnée interne, ne remplace
    jamais `name` affiché. Sur une ligne existante sans esco_uri, on la
    backfille (COALESCE) plutôt que d'écraser un éventuel match déjà présent.

    Passe `conn` pour réutiliser une connexion déjà ouverte plutôt que d'en
    ouvrir une nouvelle (voir get_competency)."""
    if conn is not None:
        existing = get_competency(student_id, name, conn=conn)
        if existing:
            if esco_uri and not existing["esco_uri"]:
                conn.execute(
                    "UPDATE student_competency SET esco_uri = %s WHERE id = %s",
                    (esco_uri, existing["id"]),
                )
                existing = get_competency(student_id, name, conn=conn)
            return existing
        conn.execute(
            """INSERT INTO student_competency
               (student_id, name, category, current_score, evaluation_count, declared, esco_uri, updated_at)
               VALUES (%s, %s, %s, 0, 0, %s, %s, %s)
               ON CONFLICT (student_id, name) DO NOTHING""",
            (student_id, name, category, int(declared), esco_uri, _now()),
        )
        return get_competency(student_id, name, conn=conn)

    existing = get_competency(student_id, name)
    if existing:
        return existing

    with get_db() as conn:
        conn.execute(
            """INSERT INTO student_competency
               (student_id, name, category, current_score, evaluation_count, declared, esco_uri, updated_at)
               VALUES (%s, %s, %s, 0, 0, %s, %s, %s)
               ON CONFLICT (student_id, name) DO NOTHING""",
            (student_id, name, category, int(declared), esco_uri, _now()),
        )
    return get_competency(student_id, name)


def seed_declared_competencies(student_id: str, names: list[str],
                                 category_map: dict[str, str] | None = None) -> None:
    """Ajoute des compétences "déclarées" (CV, chat libre) à l'arbre, sans score.

    N'écrase jamais une compétence déjà connue (déclarée ou déjà évaluée) :
    sert uniquement à peupler l'arbre pour les compétences jamais rencontrées.

    Un seul INSERT multi-lignes sur UNE connexion, quel que soit le nombre de
    compétences — la version précédente ouvrait jusqu'à 3 connexions Postgres
    PAR compétence (via get_or_create_competency), ce qui pouvait épuiser le
    pool de connexions Supabase sur un CV listant beaucoup de compétences et
    bloquer le worker gunicorn jusqu'à son timeout (30s) → 500 sans réponse
    JSON exploitable. Observé en prod sur un CV avec une longue liste de
    compétences techniques.
    """
    category_map = category_map or {}
    cleaned_names = {n.strip() for n in names if n and n.strip()}
    if not cleaned_names:
        return

    now = _now()
    # esco_engine.match_skill est une fonction pure (index en mémoire, aucun
    # accès DB) — l'appeler ici n'ajoute aucune connexion Postgres au batch.
    rows = []
    for name in cleaned_names:
        match = esco_engine.match_skill(name)
        esco_uri = match["uri"] if match else None
        rows.append((student_id, name, category_map.get(name, "autre"), 0, 0, 1, esco_uri, now))
    placeholders = ", ".join(["(%s,%s,%s,%s,%s,%s,%s,%s)"] * len(rows))
    flat_params = [value for row in rows for value in row]

    with get_db() as conn:
        conn.execute(
            f"""INSERT INTO student_competency
               (student_id, name, category, current_score, evaluation_count, declared, esco_uri, updated_at)
               VALUES {placeholders}
               ON CONFLICT (student_id, name) DO UPDATE
               SET esco_uri = COALESCE(student_competency.esco_uri, EXCLUDED.esco_uri)""",
            flat_params,
        )


def save_evaluation_history(student_competency_id: int, session_id: str, score: float,
                             feedback: str = "", conn=None) -> None:
    if conn is not None:
        conn.execute(
            """INSERT INTO competency_evaluation (student_competency_id, session_id, score, feedback, created_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (student_competency_id, session_id, score, feedback, _now()),
        )
        return
    with get_db() as conn:
        conn.execute(
            """INSERT INTO competency_evaluation (student_competency_id, session_id, score, feedback, created_at)
               VALUES (%s, %s, %s, %s, %s)""",
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

    Une seule connexion Postgres pour tout le lot de compétences (voir
    seed_declared_competencies pour le même correctif appliqué au seeding) —
    un entretien évalue plusieurs compétences d'un coup, chacune faisant
    auparavant 3 aller-retours de connexion séparés.
    """
    category_map = category_map or {}
    feedback_map = feedback_map or {}

    with get_db() as conn:
        for name, new_score in competency_scores.items():
            category = category_map.get(name, "autre")
            match = esco_engine.match_skill(name)
            esco_uri = match["uri"] if match else None
            comp = get_or_create_competency(student_id, name, category, esco_uri=esco_uri, conn=conn)

            if comp["evaluation_count"] == 0:
                updated_score = new_score
            else:
                updated_score = comp["current_score"] * (1 - RECENCY_WEIGHT) + new_score * RECENCY_WEIGHT

            conn.execute(
                """UPDATE student_competency
                   SET current_score = %s, evaluation_count = evaluation_count + 1,
                       category = %s, esco_uri = COALESCE(esco_uri, %s), updated_at = %s
                   WHERE id = %s""",
                (updated_score, category, esco_uri, _now(), comp["id"]),
            )

            save_evaluation_history(comp["id"], session_id, new_score, feedback_map.get(name, ""), conn=conn)


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

    with get_db() as conn:
        for comp in competencies:
            name = comp["name"]
            weight = comp.get("weight", 2)
            student_comp = get_competency(student_id, name, conn=conn)

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


def get_skill_rankings(student_id: str, school_id: str | None) -> dict[str, dict]:
    """Renvoie {nom_compétence: {"rank": int, "total": int}} pour les "hard
    skills" (technique/métier) de cet étudiant, comparées au reste des élèves
    RÉELLEMENT évalués sur cette même compétence dans son école.

    Anonyme par construction : seul le rang de l'étudiant appelant est
    renvoyé, jamais l'identité ni le score des autres élèves. N'affiche rien
    (dict vide pour cette compétence) si l'école a moins de
    MIN_STUDENTS_FOR_RANKING élèves évalués sur cette compétence.
    """
    if not school_id:
        return {}

    with get_db() as conn:
        rows = conn.execute(
            f"""
            WITH ranked AS (
                SELECT sc.student_id, sc.name,
                       RANK() OVER (PARTITION BY sc.name ORDER BY sc.current_score DESC) AS rank,
                       COUNT(*) OVER (PARTITION BY sc.name) AS total
                FROM student_competency sc
                JOIN users u ON u.id = sc.student_id
                WHERE u.school_id = %s
                  AND sc.category IN ({','.join(['%s'] * len(RANKING_CATEGORIES))})
                  AND sc.evaluation_count > 0
            )
            SELECT name, rank, total FROM ranked WHERE student_id = %s AND total >= %s
            """,
            (school_id, *RANKING_CATEGORIES, student_id, MIN_STUDENTS_FOR_RANKING),
        ).fetchall()

    return {row["name"]: {"rank": row["rank"], "total": row["total"]} for row in rows}


def finalize_interview_session(student_id: str, session_id: str,
                                 evaluation: dict, competency_metadata: dict[str, dict]) -> None:
    """À appeler depuis interview_routes.py juste après interviewengine.generate_final_evaluation().

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


def get_priority_skills(student_id: str, target_domain: str, current_goal: str) -> dict:
    """"3 compétences clés à maîtriser" pour l'objectif de carrière déclaré.

    Matche (target_domain + current_goal) vers le métier ESCO le plus proche,
    récupère ses compétences essentielles, et les compare à l'arbre de
    l'étudiant (via esco_uri — jamais par nom, le nom est du texte libre).
    Si l'objectif est trop vague pour un match fiable, ou l'étudiant n'a pas
    encore déclaré d'objectif, on ne force rien : {"matched_occupation": None,
    "skills": []}. Une compétence esco_uri jamais rattachée à une ligne
    existante (lignes non encore backfillées, voir seed_declared_competencies)
    apparaît comme manquante — on sous-estime la couverture plutôt que de la
    sur-estimer.
    """
    goal_text = f"{target_domain or ''} {current_goal or ''}".strip()
    if not goal_text:
        return {"matched_occupation": None, "skills": []}

    occupation = esco_engine.match_occupation(goal_text)
    if not occupation:
        return {"matched_occupation": None, "skills": []}

    essential_skills = esco_engine.get_essential_skills_for_occupation(occupation["uri"])
    if not essential_skills:
        return {"matched_occupation": occupation["pref_label"], "skills": []}

    student_by_esco_uri = {
        row["esco_uri"]: row for row in get_all_competencies(student_id) if row["esco_uri"]
    }

    missing = []
    weak = []
    for skill in essential_skills:
        comp = student_by_esco_uri.get(skill["uri"])
        if comp is None:
            missing.append({
                "name": skill["pref_label"],
                "reason": "Compétence essentielle du métier visé, absente de ton profil.",
            })
        elif comp["evaluation_count"] == 0 or comp["current_score"] < LOW_SCORE_THRESHOLD:
            weak.append({
                "name": skill["pref_label"],
                "reason": (
                    "Mentionnée mais jamais évaluée à l'oral." if comp["evaluation_count"] == 0
                    else f"Score actuel : {round(comp['current_score'])}/100."
                ),
            })

    ranked = missing + weak
    return {"matched_occupation": occupation["pref_label"], "skills": ranked[:MAX_PRIORITY_SKILLS]}
