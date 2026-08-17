"""
Fondations multi-tenant B2B2C : abonnement et appartenance à une
organisation (école), en plus du modèle existant (users.school_id,
is_school_admin — voir api/clerk_auth.py, api/routes/school_routes.py).

Coexistence délibérée, pas un remplacement : `organization_members` devient
la source de vérité pour les rôles qui n'ont pas d'équivalent aujourd'hui
(CAREER_MANAGER), mais `users.is_admin`/`is_school_admin`/`school_id`
restent lisibles et à jour — rien d'existant (dashboard école, bonus de
tokens) n'est modifié par ce module.

Pas de rôle SUPER_ADMIN ici : c'est un rôle plateforme, pas scopé à une
organisation — `users.is_admin` en reste l'unique source de vérité, comme
aujourd'hui.

`schools` reste `schools` (pas de renommage en "organizations") pour ne pas
toucher d'un coup tout le code existant qui en dépend — c'est l'entité
"organisation" du produit, juste sans renommage de table. La nouvelle table
`organization_members` utilise en revanche `organization_id` (nom aligné
sur le vocabulaire produit) en référence à `schools(id)`.
"""

from api.db import get_db

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS subscriptions (
        id                      SERIAL PRIMARY KEY,
        organization_id         TEXT NOT NULL UNIQUE REFERENCES schools(id),
        stripe_customer_id      TEXT,
        stripe_subscription_id  TEXT,
        plan_id                 TEXT,
        status                  TEXT NOT NULL DEFAULT 'trialing'
                                 CHECK (status IN ('trialing','active','past_due','canceled','expired')),
        student_limit           INTEGER,
        current_period_start    TEXT,
        current_period_end      TEXT,
        created_at              TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
        updated_at              TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organization_members (
        id              SERIAL PRIMARY KEY,
        organization_id TEXT NOT NULL REFERENCES schools(id),
        user_id         TEXT NOT NULL REFERENCES users(id),
        role            TEXT NOT NULL CHECK (role IN ('SCHOOL_ADMIN','CAREER_MANAGER','STUDENT')),
        status          TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('invited','active','suspended','removed')),
        created_at      TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
        UNIQUE(organization_id, user_id)
    )
    """,
]


def init_tables() -> None:
    """Crée les tables si absentes, puis backfille les organisations/comptes
    existants — idempotent (upserts / ON CONFLICT DO NOTHING), donc sûr à
    ré-exécuter à chaque démarrage comme le reste des migrations du projet
    (voir api/db.py::init_db()). Aucune intervention manuelle nécessaire."""
    with get_db() as conn:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)

        schools_without_subscription = conn.execute(
            """SELECT sc.id FROM schools sc
               LEFT JOIN subscriptions sub ON sub.organization_id = sc.id
               WHERE sub.id IS NULL"""
        ).fetchall()
        for school in schools_without_subscription:
            conn.execute(
                "INSERT INTO subscriptions (organization_id, status, student_limit) VALUES (%s, 'active', NULL)",
                (school["id"],),
            )

        # DO NOTHING (pas DO UPDATE) : ce backfill ne doit combler que les
        # lignes manquantes, jamais écraser un rôle déjà posé directement en
        # base (ex: un futur CAREER_MANAGER assigné manuellement, qui n'a pas
        # d'équivalent dans users.is_school_admin) — le maintien à jour sur
        # changement de rôle réel passe par upsert_membership, pas par ici.
        existing_school_members = conn.execute(
            "SELECT id, school_id, is_school_admin FROM users WHERE school_id IS NOT NULL"
        ).fetchall()
        for user in existing_school_members:
            role = "SCHOOL_ADMIN" if user["is_school_admin"] else "STUDENT"
            conn.execute(
                """INSERT INTO organization_members (organization_id, user_id, role, status)
                   VALUES (%s, %s, %s, 'active')
                   ON CONFLICT (organization_id, user_id) DO NOTHING""",
                (user["school_id"], user["id"], role),
            )


def upsert_membership(organization_id: str, user_id: str, role: str,
                       status: str = "active", conn=None) -> dict:
    """Pose/à jour le rôle d'un utilisateur dans une organisation. Contrairement
    au backfill de init_tables(), ceci EST la source de vérité sur changement
    de rôle réel (appelé aux points d'écriture existants — voir
    api/clerk_auth.py, api/routes/auth_routes.py, api/routes/admin_routes.py)
    donc DO UPDATE, pas DO NOTHING.

    Passe `conn` pour réutiliser une connexion déjà ouverte (même convention
    que api/profile_engine.py) plutôt que d'en ouvrir une nouvelle."""
    if conn is not None:
        conn.execute(
            """INSERT INTO organization_members (organization_id, user_id, role, status)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (organization_id, user_id) DO UPDATE
               SET role = EXCLUDED.role, status = EXCLUDED.status""",
            (organization_id, user_id, role, status),
        )
        return conn.execute(
            "SELECT * FROM organization_members WHERE organization_id=%s AND user_id=%s",
            (organization_id, user_id),
        ).fetchone()
    with get_db() as conn:
        return upsert_membership(organization_id, user_id, role, status, conn=conn)


def get_membership(user_id: str, conn=None) -> dict | None:
    """Un utilisateur appartient à une seule organisation aujourd'hui (même
    contrainte que users.school_id) — renvoie cette unique ligne si elle
    existe. À revoir si l'app supporte un jour l'appartenance multi-organisation."""
    if conn is not None:
        return conn.execute(
            "SELECT * FROM organization_members WHERE user_id=%s LIMIT 1", (user_id,)
        ).fetchone()
    with get_db() as conn:
        return get_membership(user_id, conn=conn)


def get_or_create_subscription(organization_id: str, conn=None) -> dict:
    if conn is not None:
        existing = conn.execute(
            "SELECT * FROM subscriptions WHERE organization_id=%s", (organization_id,)
        ).fetchone()
        if existing:
            return existing
        conn.execute(
            """INSERT INTO subscriptions (organization_id, status, student_limit)
               VALUES (%s, 'active', NULL)
               ON CONFLICT (organization_id) DO NOTHING""",
            (organization_id,),
        )
        return conn.execute(
            "SELECT * FROM subscriptions WHERE organization_id=%s", (organization_id,)
        ).fetchone()
    with get_db() as conn:
        return get_or_create_subscription(organization_id, conn=conn)


def has_active_subscription(organization_id: str) -> bool:
    """Aide centralisée d'autorisation — pas encore appelée nulle part dans
    cette passe (arrivera avec le middleware d'autorisation, Phase 3/4),
    définie maintenant pour éviter que cette logique se duplique plus tard
    dans chaque endpoint.

    active/trialing/past_due -> True (grace period simple : le statut
    past_due donne un accès complet pour l'instant, pas encore de fenêtre de
    grâce configurable — ça viendra avec le vrai câblage Stripe).
    canceled -> True seulement si la période en cours n'est pas terminée.
    expired (ou statut inconnu) -> False.
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT status,
                      (current_period_end IS NULL OR current_period_end::timestamp >= now()) AS period_still_current
               FROM subscriptions WHERE organization_id=%s""",
            (organization_id,),
        ).fetchone()
    if not row:
        return False
    if row["status"] in ("active", "trialing", "past_due"):
        return True
    if row["status"] == "canceled":
        return bool(row["period_still_current"])
    return False
