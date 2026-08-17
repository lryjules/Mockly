"""Facturation Stripe : webhook (source de vérité pour l'état d'abonnement
en base) + génération de lien de paiement côté admin plateforme.

Le webhook n'a pas de @require_auth : Stripe n'a pas de token Clerk, sa
sécurité est la vérification de signature (Stripe-Signature), pas
l'authentification applicative — voir api/stripe_gateway.py::handle_webhook_event.
"""

import stripe as stripe_sdk
from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api import stripe_gateway
from api.security import limiter, validate_length
from api.clerk_auth import require_auth, require_super_admin

billing_bp = Blueprint("billing", __name__)

MAX_PRICE_ID_LEN = 100


@billing_bp.route("/api/webhooks/stripe", methods=["POST"])
@limiter.exempt  # Stripe retente en cas de non-200 ; pas de rate limit à lui appliquer
def stripe_webhook():
    payload = request.data  # corps BRUT : request.get_json() re-sérialiserait et invaliderait la signature
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        result = stripe_gateway.handle_webhook_event(payload, sig_header)
    except stripe_sdk.error.SignatureVerificationError:
        return jsonify({"error": "Signature invalide"}), 400
    return jsonify(result), 200


@billing_bp.route("/api/admin/schools/<school_id>/payment-link", methods=["POST"])
@require_auth
@require_super_admin
@limiter.limit("20 per hour")
def create_payment_link_route(school_id):
    data = request.get_json(force=True)
    price_id = (data.get("price_id") or "").strip()
    try:
        quantity = int(data.get("quantity"))
    except (TypeError, ValueError):
        return jsonify({"error": "quantity doit être un entier (nombre de sièges)"}), 400

    if not price_id:
        return jsonify({"error": "price_id requis"}), 400
    if err := validate_length(price_id, "price_id", MAX_PRICE_ID_LEN):
        return err
    if quantity < 1:
        return jsonify({"error": "quantity doit être supérieur à 0"}), 400

    with get_db() as conn:
        school = conn.execute("SELECT id FROM schools WHERE id=%s", (school_id,)).fetchone()
    if not school:
        return jsonify({"error": "École introuvable"}), 404

    try:
        url = stripe_gateway.create_payment_link(school_id, price_id, quantity)
    except Exception as e:
        return jsonify({"error": f"Échec Stripe : {e}"}), 502

    return jsonify({"url": url})


@billing_bp.route("/api/admin/stripe/prices", methods=["GET"])
@require_auth
@require_super_admin
def list_stripe_prices_route():
    try:
        prices = stripe_gateway.list_active_prices()
    except Exception as e:
        return jsonify({"error": f"Échec Stripe : {e}"}), 502
    return jsonify(prices)
