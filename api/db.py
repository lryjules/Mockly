"""
Connexion base de données partagée par toute l'app (routes + profile_engine).
Centralise DB_PATH, get_db() et la création de toutes les tables, pour éviter
la duplication qu'on avait entre app.py et profile_engine.py.
"""

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "interview_coach.db"
UPLOADS_DIR = DATA_DIR / "uploads"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Crée toutes les tables de l'app si elles n'existent pas encore."""
    # Migration : l'ancienne table user_profiles a été renommée informations_pro
    with get_db() as conn:
        try:
            conn.execute("ALTER TABLE user_profiles RENAME TO informations_pro")
        except sqlite3.OperationalError:
            pass

    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS informations_pro (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL UNIQUE REFERENCES users(id),
            study_level   TEXT,
            target_domain TEXT,
            current_goal  TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            user_id     TEXT REFERENCES users(id),
            cv_filename TEXT,
            cv_text     TEXT,
            cv_data     TEXT,
            analysis    TEXT
        );

        CREATE TABLE IF NOT EXISTS generations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(id),
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            sector      TEXT,
            company     TEXT,
            role        TEXT,
            topics      TEXT
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(id),
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            role        TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evaluations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT NOT NULL REFERENCES sessions(id),
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            question        TEXT NOT NULL,
            user_response   TEXT NOT NULL,
            score           INTEGER,
            evaluation_json TEXT
        );

        CREATE TABLE IF NOT EXISTS job_interviews (
            id               TEXT PRIMARY KEY,
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at     TEXT,
            user_id          TEXT REFERENCES users(id),
            session_id       TEXT REFERENCES sessions(id),
            job_title        TEXT,
            job_description  TEXT NOT NULL,
            competencies     TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'in_progress',
            final_evaluation TEXT
        );

        CREATE TABLE IF NOT EXISTS job_interview_turns (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id  TEXT NOT NULL REFERENCES job_interviews(id),
            turn_index    INTEGER NOT NULL,
            competency    TEXT NOT NULL,
            question      TEXT NOT NULL,
            user_response TEXT,
            asked_at      TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """)

    with get_db() as conn:
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError:
            pass

    # Tables du profil de compétences (arbre socle)
    from api import profile_engine
    profile_engine.init_tables()