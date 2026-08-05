"""
Connexion base de données partagée par toute l'app (routes + profile_engine).
Centralise get_db() et la création de toutes les tables, pour éviter la
duplication qu'on avait entre app.py et profile_engine.py.

Base : Postgres (Supabase), lu depuis DATABASE_URL. SQLite a été abandonné
avec le passage à Supabase — le disque de Render est éphémère (repart de
zéro à chaque redéploiement), ce qui rendait le fichier .db précédent non
persistant en prod.
"""

import os
from pathlib import Path

import psycopg
from psycopg.rows import Row

DATABASE_URL = os.environ.get("DATABASE_URL", "")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)


class _FlexRow(dict):
    """Ligne accessible par nom (row["col"], comme un dict) ET par position
    (row[0]), pour rester compatible avec le code écrit à l'origine pour
    sqlite3.Row (beaucoup de `.fetchone()[0]` pour des COUNT(*) partout
    dans l'app) sans avoir à retoucher chaque appel."""
    __slots__ = ("_values",)

    def __init__(self, values, columns):
        super().__init__(zip(columns, values))
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _flex_row_factory(cursor):
    if cursor.description is None:
        # Statement sans jeu de résultat (DDL, UPDATE/INSERT sans RETURNING) :
        # aucune ligne ne sera jamais passée à make_row, peu importe sa forme.
        return lambda values: values
    columns = [c.name for c in cursor.description]

    def make_row(values):
        return _FlexRow(values, columns)
    return make_row


def get_db() -> psycopg.Connection[Row]:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL manquant : configure la chaîne de connexion Postgres "
            "(Supabase > Project Settings > Database > Connection string, mode "
            "'Session pooler') dans les variables d'environnement."
        )
    conn = psycopg.connect(DATABASE_URL, row_factory=_flex_row_factory, autocommit=False)
    return conn


# Chaque instruction séparément (pas un gros script exécuté d'un coup) :
# psycopg n'exécute fiablement plusieurs statements en un seul execute() que
# via le protocole simple, ce qu'on ne veut pas garantir ici — plus sûr et
# plus lisible de boucler sur une liste.
_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id                TEXT PRIMARY KEY,
        email             TEXT NOT NULL UNIQUE,
        password_hash     TEXT NOT NULL,
        is_admin          INTEGER NOT NULL DEFAULT 0,
        interview_credits INTEGER NOT NULL DEFAULT 3,
        coach_credits     INTEGER NOT NULL DEFAULT 3,
        created_at        TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS informations_pro (
        id            SERIAL PRIMARY KEY,
        user_id       TEXT NOT NULL UNIQUE REFERENCES users(id),
        study_level   TEXT,
        target_domain TEXT,
        current_goal  TEXT,
        created_at    TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
        updated_at    TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id          TEXT PRIMARY KEY,
        created_at  TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
        user_id     TEXT REFERENCES users(id),
        cv_filename TEXT,
        cv_text     TEXT,
        cv_data     TEXT,
        analysis    TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generations (
        id          SERIAL PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        created_at  TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
        sector      TEXT,
        company     TEXT,
        role        TEXT,
        topics      TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id          SERIAL PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES sessions(id),
        created_at  TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
        role        TEXT NOT NULL CHECK(role IN ('user','assistant')),
        content     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluations (
        id              SERIAL PRIMARY KEY,
        session_id      TEXT NOT NULL REFERENCES sessions(id),
        created_at      TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
        question        TEXT NOT NULL,
        user_response   TEXT NOT NULL,
        score           INTEGER,
        evaluation_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_interviews (
        id               TEXT PRIMARY KEY,
        created_at       TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
        completed_at     TEXT,
        user_id          TEXT REFERENCES users(id),
        session_id       TEXT REFERENCES sessions(id),
        job_title        TEXT,
        job_description  TEXT NOT NULL,
        competencies     TEXT NOT NULL,
        status           TEXT NOT NULL DEFAULT 'in_progress',
        final_evaluation TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS job_interview_turns (
        id            SERIAL PRIMARY KEY,
        interview_id  TEXT NOT NULL REFERENCES job_interviews(id),
        turn_index    INTEGER NOT NULL,
        competency    TEXT NOT NULL,
        question      TEXT NOT NULL,
        user_response TEXT,
        asked_at      TEXT,
        created_at    TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    # Journal de chaque appel IA (Gemini), pour les métriques admin : coût,
    # tokens, latence, taux d'erreur, répartition par modèle.
    """
    CREATE TABLE IF NOT EXISTS ai_call_log (
        id             SERIAL PRIMARY KEY,
        created_at     TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
        context        TEXT NOT NULL,
        model          TEXT,
        input_tokens   INTEGER,
        output_tokens  INTEGER,
        latency_ms     INTEGER,
        success        INTEGER NOT NULL DEFAULT 1,
        error_message  TEXT,
        interview_id   TEXT,
        session_id     TEXT
    )
    """,
    # Indicateurs business/pilote saisis manuellement par l'admin (aucune
    # donnée d'usage ne permet de les calculer : CRM externe).
    """
    CREATE TABLE IF NOT EXISTS business_metric (
        key        TEXT PRIMARY KEY,
        value      REAL,
        updated_at TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    # Écoles / career centers. Chaque étudiant appartient à une école
    # (users.school_id) ; chaque école a un compte de gestion dédié
    # (users.is_school_admin=1, users.school_id = l'école qu'il gère).
    """
    CREATE TABLE IF NOT EXISTS schools (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    # Invitation "profil école" en attente : posée par un admin plateforme
    # (api/routes/admin_routes.py::create_school) avant même que la personne
    # n'ait de compte Clerk. Appliquée (is_school_admin=1, school_id=...) au
    # premier login Clerk de cet email, dans clerk_auth.get_or_create_local_user,
    # puis supprimée.
    """
    CREATE TABLE IF NOT EXISTS school_admin_invites (
        email      TEXT PRIMARY KEY,
        school_id  TEXT NOT NULL REFERENCES schools(id),
        created_at TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
]

_COLUMN_MIGRATIONS = [
    "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS interview_credits INTEGER NOT NULL DEFAULT 3",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS coach_credits INTEGER NOT NULL DEFAULT 3",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS school_id TEXT REFERENCES schools(id)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_school_admin INTEGER NOT NULL DEFAULT 0",
]


def init_db() -> None:
    """Crée toutes les tables de l'app si elles n'existent pas encore."""
    with get_db() as conn:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        for statement in _COLUMN_MIGRATIONS:
            conn.execute(statement)

    # Le compte admin n'est plus bootstrappé ici : la promotion admin se fait
    # par email via CLERK_ADMIN_EMAILS, appliquée dans
    # api/clerk_auth.py::get_or_create_local_user au premier login Clerk.

    # Tables du profil de compétences (arbre socle)
    from api import profile_engine
    profile_engine.init_tables()
