"""
Connexion base de données partagée par toute l'app (routes + profile_engine).
Centralise DB_PATH, get_db() et la création de toutes les tables, pour éviter
la duplication qu'on avait entre app.py et profile_engine.py.
"""

import sqlite3
import uuid
import hashlib
from pathlib import Path

ADMIN_EMAIL = "admin@admin.com"
ADMIN_PASSWORD = "password"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "interview_coach.db"
UPLOADS_DIR = DATA_DIR / "uploads"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL : les lecteurs ne bloquent plus les écrivains (et vice-versa), ce qui
    # réduit fortement les "database is locked" quand plusieurs connexions
    # courtes coexistent (ex: journalisation des appels IA depuis un module
    # séparé pendant qu'une route tient sa propre connexion).
    conn.execute("PRAGMA journal_mode=WAL")
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
            id                TEXT PRIMARY KEY,
            email             TEXT NOT NULL UNIQUE,
            password_hash     TEXT NOT NULL,
            is_admin          INTEGER NOT NULL DEFAULT 0,
            interview_credits INTEGER NOT NULL DEFAULT 3,
            coach_credits     INTEGER NOT NULL DEFAULT 3,
            created_at        TEXT NOT NULL DEFAULT (datetime('now'))
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

        -- Journal de chaque appel IA (Gemini), pour les métriques admin :
        -- coût, tokens, latence, taux d'erreur, répartition par modèle.
        CREATE TABLE IF NOT EXISTS ai_call_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            context        TEXT NOT NULL,   -- ex: 'cv_parse', 'interview_question', 'interview_eval', 'chat', 'stt'
            model          TEXT,
            input_tokens   INTEGER,
            output_tokens  INTEGER,
            latency_ms     INTEGER,
            success        INTEGER NOT NULL DEFAULT 1,
            error_message  TEXT,
            interview_id   TEXT,
            session_id     TEXT
        );

        -- Indicateurs business/pilote saisis manuellement par l'admin
        -- (aucune donnée d'usage ne permet de les calculer : CRM externe).
        CREATE TABLE IF NOT EXISTS business_metric (
            key        TEXT PRIMARY KEY,
            value      REAL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """)

    with get_db() as conn:
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN interview_credits INTEGER NOT NULL DEFAULT 3")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE users ADD COLUMN coach_credits INTEGER NOT NULL DEFAULT 3")
        except sqlite3.OperationalError:
            pass

    _ensure_admin_account()

    # Tables du profil de compétences (arbre socle)
    from api import profile_engine
    profile_engine.init_tables()


def _ensure_admin_account() -> None:
    """Crée (ou promeut) le compte admin@admin.com au démarrage, pour que le
    tableau de bord admin soit accessible sans étape de configuration manuelle."""
    password_hash = hashlib.sha256(ADMIN_PASSWORD.encode("utf-8")).hexdigest()
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email=?", (ADMIN_EMAIL,)).fetchone()
        if existing:
            conn.execute("UPDATE users SET is_admin=1 WHERE email=?", (ADMIN_EMAIL,))
        else:
            conn.execute(
                "INSERT INTO users (id, email, password_hash, is_admin) VALUES (?,?,?,1)",
                (str(uuid.uuid4()), ADMIN_EMAIL, password_hash)
            )