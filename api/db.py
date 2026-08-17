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
from flask import g, has_app_context

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


def _connect() -> psycopg.Connection[Row]:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL manquant : configure la chaîne de connexion Postgres "
            "(Supabase > Project Settings > Database > Connection string, mode "
            "'Session pooler') dans les variables d'environnement."
        )
    try:
        return psycopg.connect(
            DATABASE_URL, row_factory=_flex_row_factory, autocommit=False, connect_timeout=10
        )
    except psycopg.OperationalError as e:
        # Cas fréquent : DATABASE_URL pointe sur la connexion "Direct" de
        # Supabase (db.<ref>.supabase.co), qui ne résout qu'en IPv6 — injoignable
        # depuis un hébergeur (ex. Render) sans sortie IPv6. Le "Session pooler"
        # (host ...pooler.supabase.com) résout en IPv4 et règle le problème.
        raise RuntimeError(
            "Connexion à la base impossible (réseau injoignable). Si l'URL pointe "
            "sur 'db.<ref>.supabase.co' (connexion directe, IPv6 uniquement), "
            "utilise plutôt le 'Session pooler' de Supabase (host "
            "'...pooler.supabase.com'), compatible IPv4."
        ) from e


class _RequestScopedConn:
    """Proxy retourné par get_db() : réutilise LA MÊME connexion Postgres
    pour tous les get_db() d'une même requête Flask (stockée dans `g`) au
    lieu d'en ouvrir une nouvelle à chaque appel — un handler typique en
    ouvrait 2 à 7 (une par accès DB, plus une par appel IA rien que pour la
    journalisation), chacune payant une poignée de main TCP+TLS+Postgres
    complète vers le pooler Supabase.

    Seul le `with` le plus englobant (premier entré) commit/rollback pour de
    vrai à la sortie — les appels imbriqués (ex: seed_declared_competencies
    appelé depuis l'intérieur d'un autre `with get_db()`) réutilisent la
    connexion sans clôturer prématurément la transaction du bloc englobant.
    La connexion physique n'est fermée qu'au teardown de la requête
    (voir close_request_db, enregistré dans app.py)."""

    def __enter__(self) -> psycopg.Connection[Row]:
        conn = getattr(g, "_db_conn", None)
        if conn is None or conn.closed:
            conn = _connect()
            g._db_conn = conn
        g._db_depth = getattr(g, "_db_depth", 0) + 1
        self._is_outermost = g._db_depth == 1
        self._conn = conn
        return conn

    def __exit__(self, exc_type, exc, tb):
        g._db_depth -= 1
        if self._is_outermost:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        return False


def get_db() -> psycopg.Connection[Row]:
    """Hors contexte de requête Flask (scripts, init_db() au démarrage) :
    connexion classique, une par appel, fermée à la sortie du `with` — pas
    de `g` à accrocher. Dans une requête : voir _RequestScopedConn ci-dessus."""
    if has_app_context():
        return _RequestScopedConn()
    return _connect()


def close_request_db(_exc=None) -> None:
    """Ferme la connexion partagée de la requête, si une a été ouverte.
    À enregistrer via app.teardown_appcontext (voir app.py)."""
    conn = g.pop("_db_conn", None)
    if conn is not None and not conn.closed:
        conn.close()


# Chaque instruction séparément (pas un gros script exécuté d'un coup) :
# psycopg n'exécute fiablement plusieurs statements en un seul execute() que
# via le protocole simple, ce qu'on ne veut pas garantir ici — plus sûr et
# plus lisible de boucler sur une liste.
_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id                      TEXT PRIMARY KEY,
        email                   TEXT NOT NULL UNIQUE,
        password_hash           TEXT NOT NULL,
        is_admin                INTEGER NOT NULL DEFAULT 0,
        bonus_daily_token_limit INTEGER NOT NULL DEFAULT 0,
        created_at              TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
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
        session_id     TEXT,
        user_id        TEXT
    )
    """,
    # Compteur de tokens IA consommés par jour et par étudiant, pour le quota
    # journalier (api/token_budget.py). Une ligne par (user_id, usage_date),
    # incrémentée à chaque appel Gemini réellement effectué.
    """
    CREATE TABLE IF NOT EXISTS token_usage_daily (
        user_id     TEXT NOT NULL,
        usage_date  TEXT NOT NULL,
        tokens_used INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, usage_date)
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
        id                        TEXT PRIMARY KEY,
        name                      TEXT NOT NULL UNIQUE,
        monthly_bonus_token_pool  INTEGER NOT NULL DEFAULT 1000000,
        monthly_bonus_tokens_used INTEGER NOT NULL DEFAULT 0,
        monthly_bonus_reset_month TEXT NOT NULL DEFAULT '',
        created_at                TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
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
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS school_id TEXT REFERENCES schools(id)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_school_admin INTEGER NOT NULL DEFAULT 0",
    # Remplace le système de crédits par un quota de tokens IA quotidien
    # (voir api/token_budget.py) : les anciennes colonnes de crédits sont
    # abandonnées, remplacées par un bonus quotidien accordé par l'école.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_daily_token_limit INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users DROP COLUMN IF EXISTS interview_credits",
    "ALTER TABLE users DROP COLUMN IF EXISTS coach_credits",
    "ALTER TABLE schools ADD COLUMN IF NOT EXISTS monthly_bonus_token_pool INTEGER NOT NULL DEFAULT 1000000",
    "ALTER TABLE schools ADD COLUMN IF NOT EXISTS monthly_bonus_tokens_used INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE schools ADD COLUMN IF NOT EXISTS monthly_bonus_reset_month TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE ai_call_log ADD COLUMN IF NOT EXISTS user_id TEXT",
    # Fondations multi-tenant (voir api/organizations.py) : statut opérationnel
    # de l'organisation, distinct du statut d'abonnement (table subscriptions).
    "ALTER TABLE schools ADD COLUMN IF NOT EXISTS slug TEXT",
    "ALTER TABLE schools ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'",
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

    # Fondations multi-tenant (organisation/rôles/abonnement)
    from api import organizations
    organizations.init_tables()
