"""
Authentification via Clerk (https://clerk.com) : remplace l'ancien modèle
"user_id envoyé tel quel par le client" par une vraie vérification de session
côté serveur.

Le frontend récupère un token de session Clerk (JS SDK, `Clerk.session.getToken()`)
et l'envoie dans l'en-tête `Authorization: Bearer <token>` de chaque requête API.
`require_auth` vérifie ce token (signature + expiration, via le SDK officiel qui
gère le JWKS de l'instance Clerk) et expose l'identité vérifiée dans `g.clerk_user_id`.

Notre table `users` reste la source de vérité pour tout ce que Clerk ne gère pas
(rôle admin/école, crédits) : `get_or_create_local_user` la synchronise à la
volée au premier passage d'un utilisateur Clerk jamais vu.
"""

import os
from functools import wraps

from flask import request, jsonify, g
from clerk_backend_api import Clerk
from clerk_backend_api.security.types import AuthenticateRequestOptions

from api.db import get_db
from api import organizations

CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")
CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
# Optionnelle (Clerk Dashboard > API Keys > Advanced > "JWT public key") :
# si fournie, le SDK vérifie la signature du token localement (RSA, la clé
# publique ne change pas) au lieu d'aller chercher le JWKS sur les serveurs
# Clerk. Sans elle, le SDK fait cet appel réseau au premier token vu par
# chaque worker puis le met en cache 5 min — donc déjà peu coûteux en usage
# normal, mais notable juste après un cold start (Render free tier).
CLERK_JWT_KEY = os.environ.get("CLERK_JWT_KEY", "")

# Domaines autorisés à présenter un token Clerk à cette API (anti-rejeu depuis
# un autre site). Ex: "http://localhost:5001,https://mockly.onrender.com".
_AUTHORIZED_PARTIES = [
    p.strip() for p in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",") if p.strip()
]

# Comptes considérés admin dès leur première connexion Clerk (par email) —
# remplace l'ancien admin@admin.com/password codé en dur. Ex: "toi@exemple.com".
_ADMIN_EMAILS = {
    e.strip().lower() for e in os.environ.get("CLERK_ADMIN_EMAILS", "").split(",") if e.strip()
}

_clerk_client = Clerk(bearer_auth=CLERK_SECRET_KEY) if CLERK_SECRET_KEY else None


def is_configured() -> bool:
    return _clerk_client is not None


def _auth_options() -> AuthenticateRequestOptions:
    return AuthenticateRequestOptions(
        secret_key=CLERK_SECRET_KEY,
        jwt_key=CLERK_JWT_KEY or None,
        authorized_parties=_AUTHORIZED_PARTIES or None,
    )


def require_auth(f):
    """Vérifie le token Clerk de la requête ; sinon 401. Expose `g.clerk_user_id`."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _clerk_client:
            return jsonify({"error": "Authentification non configurée côté serveur (CLERK_SECRET_KEY manquant)"}), 500

        options = _auth_options()
        try:
            state = _clerk_client.authenticate_request(request, options)
        except Exception:
            return jsonify({"error": "Session invalide"}), 401

        if not state.is_signed_in or not state.payload:
            return jsonify({"error": "Authentification requise"}), 401

        g.clerk_user_id = state.payload.get("sub")
        if not g.clerk_user_id:
            return jsonify({"error": "Authentification requise"}), 401

        return f(*args, **kwargs)
    return wrapper


def optional_auth(f):
    """Comme require_auth, mais laisse passer sans identité si aucun token
    n'est fourni (g.clerk_user_id = None) — pour les routes accessibles en
    partie sans connexion."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        g.clerk_user_id = None
        auth_header = request.headers.get("Authorization", "")
        if _clerk_client and auth_header.startswith("Bearer "):
            options = _auth_options()
            try:
                state = _clerk_client.authenticate_request(request, options)
                if state.is_signed_in and state.payload:
                    g.clerk_user_id = state.payload.get("sub")
            except Exception:
                pass
        return f(*args, **kwargs)
    return wrapper


def require_super_admin(f):
    """Remplace le pattern répété `if not _is_admin(g.clerk_user_id): 403`
    (api/routes/admin_routes.py) par un décorateur unique. À empiler APRÈS
    @require_auth (a besoin de g.clerk_user_id déjà posé)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        row = get_or_create_local_user(g.clerk_user_id)
        if not row or not row["is_admin"]:
            return jsonify({"error": "Accès réservé aux administrateurs"}), 403
        return f(*args, **kwargs)
    return wrapper


def require_org_role(*allowed_roles: str, require_subscription: bool = False):
    """Remplace _get_school_admin (api/routes/school_routes.py). Expose
    g.organization_id / g.org_membership au handler. require_subscription=True
    ajoute le contrôle organizations.has_active_subscription (402 si
    l'abonnement de l'organisation n'est plus actif). À empiler APRÈS
    @require_auth.

    Appelle get_or_create_local_user AVANT de lire organization_members :
    c'est ce qui déclenche l'application d'une invitation en attente
    (_apply_pending_org_invite) — sans cet appel, le tout premier login d'un
    compte fraîchement invité échouerait (son invitation ne serait jamais
    consommée avant la vérification du rôle)."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            get_or_create_local_user(g.clerk_user_id)
            membership = organizations.get_membership(g.clerk_user_id)
            if not membership or membership["role"] not in allowed_roles or membership["status"] != "active":
                return jsonify({"error": "Accès non autorisé"}), 403
            if require_subscription and not organizations.has_active_subscription(membership["organization_id"]):
                return jsonify({"error": "Abonnement de l'organisation inactif ou expiré"}), 402
            g.organization_id = membership["organization_id"]
            g.org_membership = membership
            return f(*args, **kwargs)
        return wrapper
    return decorator


def _fetch_clerk_email(clerk_user_id: str) -> str:
    try:
        user = _clerk_client.users.get(user_id=clerk_user_id)
        primary_id = getattr(user, "primary_email_address_id", None)
        for addr in (getattr(user, "email_addresses", None) or []):
            if primary_id is None or addr.id == primary_id:
                return addr.email_address
        # Repli : première adresse connue si pas d'adresse primaire identifiée.
        addrs = getattr(user, "email_addresses", None) or []
        return addrs[0].email_address if addrs else ""
    except Exception:
        return ""


def get_or_create_local_user(clerk_user_id: str) -> dict:
    """Renvoie la ligne locale `users` liée à cet utilisateur Clerk, en la
    créant (avec les crédits par défaut) si c'est la première fois qu'on le voit.
    Ne force jamais school_id : un compte fraîchement provisionné doit encore
    choisir son école côté front avant d'accéder au workspace."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=%s", (clerk_user_id,)).fetchone()
        if row:
            changed = False
            # Promotion admin si l'email correspond à l'allowlist, même pour un
            # compte déjà provisionné (ex: ajouté à CLERK_ADMIN_EMAILS après coup).
            if row["email"] and row["email"].lower() in _ADMIN_EMAILS and not row["is_admin"]:
                conn.execute("UPDATE users SET is_admin=1 WHERE id=%s", (clerk_user_id,))
                changed = True
            changed = _apply_pending_org_invite(conn, clerk_user_id, row["email"]) or changed
            if changed:
                row = conn.execute("SELECT * FROM users WHERE id=%s", (clerk_user_id,)).fetchone()
            return dict(row)

        email = _fetch_clerk_email(clerk_user_id) or f"{clerk_user_id}@clerk.local"
        is_admin = 1 if email.lower() in _ADMIN_EMAILS else 0
        conn.execute(
            "INSERT INTO users (id, email, password_hash, is_admin) VALUES (%s,%s,%s,%s)",
            (clerk_user_id, email, "", is_admin)
        )
        conn.execute("INSERT INTO informations_pro (user_id) VALUES (%s)", (clerk_user_id,))
        _apply_pending_org_invite(conn, clerk_user_id, email)
        row = conn.execute("SELECT * FROM users WHERE id=%s", (clerk_user_id,)).fetchone()
        return dict(row)


def session_owned_by_current_user(conn, session_id: str) -> bool:
    """Une session non rattachée à un compte (user_id NULL, legacy/anonyme)
    reste accessible sans vérification ; sinon elle doit appartenir à
    g.clerk_user_id. Utilisé par toutes les routes qui opèrent sur une
    `sessions.id` (chat, topics, interview) pour empêcher qu'un utilisateur
    connecté agisse sur la session CV de quelqu'un d'autre en devinant son UUID."""
    row = conn.execute("SELECT user_id FROM sessions WHERE id=%s", (session_id,)).fetchone()
    if not row:
        return False
    return not row["user_id"] or row["user_id"] == g.clerk_user_id


def _apply_pending_org_invite(conn, clerk_user_id: str, email: str) -> bool:
    """Si un admin (plateforme ou école) a invité cet email avant qu'il n'ait
    de compte Clerk (ou avant sa première visite), applique l'invitation en
    attente — quel que soit le rôle (SCHOOL_ADMIN, CAREER_MANAGER, STUDENT),
    voir api/organizations.py::send_org_invite."""
    if not email:
        return False
    invite = conn.execute(
        "SELECT organization_id, role FROM pending_org_invites WHERE email=%s", (email.lower(),)
    ).fetchone()
    if not invite:
        return False
    is_school_admin = 1 if invite["role"] == "SCHOOL_ADMIN" else 0
    conn.execute(
        "UPDATE users SET is_school_admin=%s, school_id=%s WHERE id=%s",
        (is_school_admin, invite["organization_id"], clerk_user_id)
    )
    conn.execute("DELETE FROM pending_org_invites WHERE email=%s", (email.lower(),))
    organizations.upsert_membership(invite["organization_id"], clerk_user_id, invite["role"], conn=conn)
    return True
