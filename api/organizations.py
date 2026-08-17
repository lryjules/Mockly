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
    # Remplace school_admin_invites (généralisée à tout rôle, plus seulement
    # SCHOOL_ADMIN) : invitation posée avant que la personne n'ait de compte
    # Clerk, consommée à son premier login (voir
    # api/clerk_auth.py::_apply_pending_org_invite). first_name/last_name
    # permettent d'afficher un roster lisible avant même l'inscription.
    """
    CREATE TABLE IF NOT EXISTS pending_org_invites (
        email           TEXT PRIMARY KEY,
        organization_id TEXT NOT NULL REFERENCES schools(id),
        role            TEXT NOT NULL CHECK (role IN ('SCHOOL_ADMIN','CAREER_MANAGER','STUDENT')),
        first_name      TEXT,
        last_name       TEXT,
        invited_by      TEXT REFERENCES users(id),
        created_at      TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
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

        # Reprend les invitations encore en attente dans l'ancienne table
        # (school_admin_invites) — aucune n'est perdue au renommage/généralisation.
        # L'ancienne table n'est pas supprimée automatiquement (DROP TABLE est
        # une opération destructive, à faire manuellement une fois la bascule
        # confirmée en prod).
        legacy_invites = conn.execute("SELECT email, school_id FROM school_admin_invites").fetchall()
        for invite in legacy_invites:
            conn.execute(
                """INSERT INTO pending_org_invites (email, organization_id, role)
                   VALUES (%s, %s, 'SCHOOL_ADMIN')
                   ON CONFLICT (email) DO NOTHING""",
                (invite["email"], invite["school_id"]),
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


def get_seat_usage(organization_id: str, conn=None) -> dict:
    """{"used": int, "limit": int|None}. Un siège est compté dès l'invitation,
    pas seulement à l'activation — sinon un admin pourrait inviter largement
    au-delà de sa capacité sans jamais être bloqué avant que les invités
    n'acceptent. Somme de deux sources plutôt qu'une ligne organization_members
    par invité : organization_members.user_id est NOT NULL (référence un
    compte réel), donc impossible d'y représenter un invité qui n'a pas encore
    de compte Clerk — pending_org_invites EST la réservation de siège tant que
    l'invitation n'est pas consommée (voir send_org_invite /
    api/clerk_auth.py::_apply_pending_org_invite, qui supprime la ligne
    pending_org_invites exactement quand la ligne organization_members
    'active' correspondante est créée — jamais de double-comptage)."""
    if conn is not None:
        active = conn.execute(
            """SELECT COUNT(*) FROM organization_members
               WHERE organization_id=%s AND role='STUDENT' AND status='active'""",
            (organization_id,),
        ).fetchone()[0]
        invited = conn.execute(
            "SELECT COUNT(*) FROM pending_org_invites WHERE organization_id=%s AND role='STUDENT'",
            (organization_id,),
        ).fetchone()[0]
        sub = conn.execute(
            "SELECT student_limit FROM subscriptions WHERE organization_id=%s", (organization_id,)
        ).fetchone()
        return {"used": active + invited, "limit": sub["student_limit"] if sub else None}
    with get_db() as conn:
        return get_seat_usage(organization_id, conn=conn)


def has_available_seats(organization_id: str, additional: int = 1, conn=None) -> bool:
    """limit=None -> illimité (valeur par défaut à la création d'une école,
    voir get_or_create_subscription) -> toujours True."""
    usage = get_seat_usage(organization_id, conn=conn)
    if usage["limit"] is None:
        return True
    return usage["used"] + additional <= usage["limit"]


def send_org_invite(email: str, organization_id: str, role: str,
                     invited_by: str | None = None,
                     first_name: str | None = None, last_name: str | None = None,
                     conn=None) -> dict:
    """Rattache immédiatement un compte Clerk déjà existant sans école, sinon
    envoie une vraie invitation par email via l'API Clerk (le client Clerk
    est importé ici, pas en haut du fichier, pour éviter un import circulaire
    avec api/clerk_auth.py qui importe déjà ce module).

    Renvoie {"status": "applied"|"pending"|"already_member"|"conflict"|"failed", "reason"?: str}.
    Ne laisse jamais de ligne pending_org_invites orpheline si l'appel Clerk échoue."""
    if conn is None:
        with get_db() as conn:
            return send_org_invite(email, organization_id, role, invited_by, first_name, last_name, conn=conn)

    existing_user = conn.execute("SELECT id, school_id FROM users WHERE email=%s", (email,)).fetchone()
    if existing_user:
        if existing_user["school_id"] == organization_id:
            return {"status": "already_member"}
        if existing_user["school_id"]:
            return {"status": "conflict", "reason": "Cet email appartient déjà à une autre organisation"}
        conn.execute(
            "UPDATE users SET school_id=%s, is_school_admin=%s WHERE id=%s",
            (organization_id, 1 if role == "SCHOOL_ADMIN" else 0, existing_user["id"]),
        )
        upsert_membership(organization_id, existing_user["id"], role, conn=conn)
        return {"status": "applied"}

    if conn.execute("SELECT email FROM pending_org_invites WHERE email=%s", (email,)).fetchone():
        return {"status": "already_member", "reason": "Invitation déjà en attente pour cet email"}

    conn.execute(
        """INSERT INTO pending_org_invites (email, organization_id, role, first_name, last_name, invited_by)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (email, organization_id, role, first_name, last_name, invited_by),
    )

    from api.clerk_auth import _clerk_client
    if _clerk_client is None:
        conn.execute("DELETE FROM pending_org_invites WHERE email=%s", (email,))
        return {"status": "failed", "reason": "Authentification Clerk non configurée côté serveur"}
    try:
        _clerk_client.invitations.create(request={
            "email_address": email,
            "public_metadata": {"organization_id": organization_id, "role": role},
        })
    except Exception as e:
        conn.execute("DELETE FROM pending_org_invites WHERE email=%s", (email,))
        return {"status": "failed", "reason": str(e)}

    return {"status": "pending"}
