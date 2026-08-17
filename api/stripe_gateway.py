"""
Facturation via Stripe — lien de paiement (pas de checkout intégré à la
plateforme, cf. décision produit : vente B2B2C à cycle commercial, pas de
self-service carte bancaire) + synchronisation des webhooks vers
api/organizations.py::subscriptions (source de vérité locale pour
l'autorisation, jamais Stripe directement — voir has_active_subscription).

Chaque Payment Link porte organization_id en métadonnée, à la fois sur le
Payment Link lui-même ET sur `subscription_data.metadata` (copié
déclarativement sur l'objet Subscription généré) : les événements
`customer.subscription.*` portent donc organization_id directement dans
`event.data.object.metadata`, sans avoir besoin de corréler par
stripe_customer_id/stripe_subscription_id. C'est le mécanisme de
rattachement, pas une simple donnée décorative.
"""

import os

import stripe

from api.db import get_db
from api import organizations

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

stripe.api_key = STRIPE_SECRET_KEY

# Statuts Stripe -> les 5 valeurs acceptées par le CHECK constraint de
# subscriptions.status (voir api/organizations.py). incomplete/incomplete_expired
# volontairement absents : une session jamais aboutie ne doit toucher aucune
# ligne existante (voir handle_webhook_event).
_STATUS_MAP = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "canceled": "canceled",
    "unpaid": "past_due",
    "paused": "past_due",
}

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS stripe_webhook_events (
        id         TEXT PRIMARY KEY,
        type       TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
    )
    """,
]


def init_tables() -> None:
    with get_db() as conn:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)


def is_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


def create_payment_link(organization_id: str, price_id: str, quantity: int) -> str:
    """Lève l'exception Stripe telle quelle en cas d'échec — pas de fallback
    silencieux, même politique que le reste de l'app (voir api/ai_gateway.py)."""
    link = stripe.PaymentLink.create(
        line_items=[{"price": price_id, "quantity": quantity}],
        metadata={"organization_id": organization_id},
        subscription_data={"metadata": {"organization_id": organization_id}},
    )
    return link.url


def list_active_prices() -> list[dict]:
    prices = stripe.Price.list(active=True, expand=["data.product"], limit=100)
    result = []
    for p in prices.data:
        product_name = p.product.name if hasattr(p.product, "name") else str(p.product)
        result.append({
            "id": p.id,
            "nickname": p.nickname,
            "product_name": product_name,
            "unit_amount": p.unit_amount,
            "currency": p.currency,
            "interval": p.recurring.interval if p.recurring else None,
        })
    return result


def _apply_subscription_event(subscription: dict, conn) -> bool:
    """Retourne False si l'événement n'a pas pu être rattaché à une
    organisation (metadata absente — ex: abonnement créé hors Payment Link
    Mockly) ou si le statut Stripe n'a pas d'équivalent actionnable
    (incomplete/incomplete_expired). Ne touche alors AUCUNE ligne existante."""
    organization_id = (subscription.get("metadata") or {}).get("organization_id")
    if not organization_id:
        return False

    stripe_status = subscription.get("status")
    mapped_status = _STATUS_MAP.get(stripe_status)
    if not mapped_status:
        return False

    items = (subscription.get("items") or {}).get("data") or []
    item = items[0] if items else {}
    quantity = item.get("quantity")
    price = item.get("price") or {}
    plan_id = price.get("id")
    period_start = item.get("current_period_start")
    period_end = item.get("current_period_end")

    organizations.get_or_create_subscription(organization_id, conn=conn)
    conn.execute(
        """UPDATE subscriptions
           SET status=%s, student_limit=COALESCE(%s, student_limit),
               plan_id=COALESCE(%s, plan_id),
               stripe_customer_id=%s, stripe_subscription_id=%s,
               current_period_start=to_timestamp(%s)::text,
               current_period_end=to_timestamp(%s)::text,
               updated_at=to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
           WHERE organization_id=%s""",
        (
            mapped_status, quantity, plan_id,
            subscription.get("customer"), subscription.get("id"),
            period_start, period_end,
            organization_id,
        ),
    )
    return True


def _apply_subscription_deleted(subscription: dict, conn) -> bool:
    """Un abonnement supprimé côté Stripe doit bloquer l'accès immédiatement
    (pas 'canceled', qui dans notre modèle garde l'accès jusqu'à la fin de la
    période en cours — à ce stade Stripe a déjà définitivement clos
    l'abonnement)."""
    organization_id = (subscription.get("metadata") or {}).get("organization_id")
    if not organization_id:
        return False
    conn.execute(
        """UPDATE subscriptions SET status='expired', updated_at=to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
           WHERE organization_id=%s""",
        (organization_id,),
    )
    return True


def _apply_invoice_payment_failed(invoice: dict, conn) -> bool:
    """L'organization_id vit sur la métadonnée de la subscription, dont
    l'invoice ne porte qu'un instantané (parent.subscription_details.metadata,
    figé à la création de l'invoice) — repli sur stripe_subscription_id si
    absent (invoice plus ancienne, ou instantané non peuplé)."""
    parent = invoice.get("parent") or {}
    sub_details = parent.get("subscription_details") or {}
    organization_id = (sub_details.get("metadata") or {}).get("organization_id")
    subscription_id = sub_details.get("subscription")

    if organization_id:
        conn.execute(
            """UPDATE subscriptions SET status='past_due', updated_at=to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
               WHERE organization_id=%s""",
            (organization_id,),
        )
        return True
    if subscription_id:
        updated = conn.execute(
            """UPDATE subscriptions SET status='past_due', updated_at=to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
               WHERE stripe_subscription_id=%s""",
            (subscription_id,),
        )
        return updated.rowcount > 0
    return False


def handle_webhook_event(payload: bytes, sig_header: str) -> dict:
    """Lève stripe.error.SignatureVerificationError si la signature est
    invalide — à la charge de l'appelant (route) de renvoyer 400 sans
    traiter le payload. Idempotent : un event.id déjà vu n'est jamais
    retraité (voir stripe_webhook_events)."""
    event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)

    with get_db() as conn:
        inserted = conn.execute(
            "INSERT INTO stripe_webhook_events (id, type) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (event.id, event.type),
        )
        if inserted.rowcount == 0:
            return {"handled": False, "type": event.type, "reason": "already_processed"}

        # StripeObject n'hérite pas de dict (pas de .get() natif) — to_dict()
        # récursif convertit tout l'arbre en dicts/listes Python standard,
        # ce dont dépendent les _apply_* ci-dessus.
        obj = event.data.object.to_dict()
        handled = False
        if event.type in ("customer.subscription.created", "customer.subscription.updated"):
            handled = _apply_subscription_event(obj, conn)
        elif event.type == "customer.subscription.deleted":
            handled = _apply_subscription_deleted(obj, conn)
        elif event.type == "invoice.payment_failed":
            handled = _apply_invoice_payment_failed(obj, conn)

    return {"handled": handled, "type": event.type}
