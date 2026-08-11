"""
Interview Coach - Flask Backend

Ce fichier ne contient plus que la configuration de l'app et l'enregistrement
des blueprints. Toute la logique métier vit dans api/routes/*.py, api/db.py,
api/profile_engine.py, api/profileprocessing.py et api/interviewengine.py.

Routes (voir api/routes/ pour le détail) :
  auth_routes       → /api/signup, /api/login
  cv_routes         → /api/upload-cv
  topics_routes     → /api/generate-interview-topics
  chat_routes       → /api/start-chat, /api/chat, /api/evaluate-response
  interview_routes  → /api/interview/start, /respond, /finish
  profile_routes    → /api/informations-pro, /api/profile/readiness-check, /api/profile/competencies/<user_id>
  sessions_routes   → /api/sessions, /api/sessions/<id>
  admin_routes      → /api/admin/kpis, /api/admin/business-metrics
  school_routes     → /api/school/dashboard, /api/school/students/<id>/credits, /api/school/credits/bulk
  pages_routes      → sert le frontend (/, /results, /interview, /configuration, /admin)
"""

import os
import traceback

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, request
from flask_cors import CORS

from api.db import init_db, close_request_db
from api import ai_gateway
from api.security import limiter

from api.routes.auth_routes import auth_bp
from api.routes.cv_routes import cv_bp
from api.routes.topics_routes import topics_bp
from api.routes.chat_routes import chat_bp
from api.routes.interview_routes import interview_bp
from api.routes.profile_routes import profile_bp
from api.routes.sessions_routes import sessions_bp
from api.routes.admin_routes import admin_bp
from api.routes.school_routes import school_bp
from api.routes.pages_routes import pages_bp

app = Flask(__name__, static_folder=None)

# Le front est servi par cette même app (pages_routes) : aucune requête
# cross-origin n'est nécessaire en usage normal. On n'active CORS que si
# ALLOWED_ORIGINS est explicitement configurée (ex. front séparé), pour ne
# pas laisser n'importe quel site tiers appeler l'API depuis le navigateur
# d'un utilisateur.
_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _allowed_origins:
    CORS(app, origins=_allowed_origins)

# Capuchon global sur la taille de toute requête (upload CV, audio d'entretien
# compris) : au-delà, Flask coupe la connexion avant même de lire le corps.
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 Mo

# Sans ça, send_from_directory (pages_routes.py) n'ajoute aucun Cache-Control :
# chaque navigation entre pages re-télécharge styles.css/*.js pour rien. Pas
# de hash dans les noms de fichiers ici (pas de build step), donc on reste
# modéré (5 min) plutôt qu'un cache long — un déploiement se propage vite
# sans qu'un visiteur reste bloqué sur une vieille version trop longtemps.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 300

limiter.init_app(app)

# Une seule connexion Postgres réutilisée par tous les get_db() d'une même
# requête (voir api/db.py::_RequestScopedConn), fermée ici à la fin de
# chaque requête — avant, chaque get_db() ouvrait sa propre connexion,
# jusqu'à 5-7 par requête (voir commit sur la latence).
app.teardown_appcontext(close_request_db)


@app.errorhandler(413)
def handle_payload_too_large(e):
    return jsonify({"error": "Fichier ou requête trop volumineux (max 15 Mo)"}), 413


@app.errorhandler(429)
def handle_rate_limited(e):
    return jsonify({"error": "Trop de requêtes, réessaie dans quelques instants"}), 429


@app.errorhandler(404)
def handle_not_found(e):
    # Ne s'applique qu'aux routes /api/* : pages_routes gère déjà le reste
    # (catch-all qui sert le frontend statique) et n'appelle jamais ce handler
    # pour des fichiers manquants côté navigateur classique.
    if request.path.startswith("/api/"):
        return jsonify({"error": "Ressource introuvable"}), 404
    return e, 404


@app.errorhandler(500)
def handle_server_error(e):
    # Historique : une erreur non-JSON ici (page HTML Flask par défaut) casse
    # le frontend, qui fait toujours `response.json()` sans vérifier le
    # content-type ("Unexpected token '<' ... is not valid JSON").
    # Trace explicitement sur stdout (visible dans les logs Render) : sans ça,
    # une exception non prévue par une route donne "Erreur serveur interne"
    # sans aucun moyen de savoir pourquoi, ni ici ni côté client.
    print(f"[500] {request.method} {request.path} :")
    traceback.print_exc()
    if request.path.startswith("/api/"):
        return jsonify({"error": "Erreur serveur interne"}), 500
    return e, 500


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # microphone=(self) : requis par l'entretien audio (getUserMedia côté /interview).
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(self)"
    return response


app.register_blueprint(auth_bp)
app.register_blueprint(cv_bp)
app.register_blueprint(topics_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(interview_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(school_bp)
app.register_blueprint(pages_bp)  # toujours en dernier : contient la route catch-all "/<path:path>"

# pages_bp sert le HTML/CSS/JS statique (et le catch-all) : jamais de raison
# de le rate-limiter comme les endpoints /api/*, sous peine qu'un simple
# rechargement de page (plusieurs fichiers requêtés d'un coup) déclenche des
# 429 sur des .css/.js — le navigateur les reçoit alors avec un
# Content-Type JSON et refuse de les appliquer/exécuter.
limiter.exempt(pages_bp)

# Doit s'exécuter à l'import du module, pas seulement sous __main__ : gunicorn
# (utilisé en prod, ex. sur Render) importe `app` sans jamais passer par le
# bloc __main__ ci-dessous, donc les tables ne seraient jamais créées sinon.
init_db()


if __name__ == "__main__":
    from api.db import DATABASE_URL
    key_status = "✅ configurée" if ai_gateway.GEMINI_API_KEY else "❌ non configurée (mode mock)"
    db_status = "✅ configurée" if DATABASE_URL else "❌ DATABASE_URL manquant"
    print(f"""
╔═══════════════════════════════════════════╗
║       Interview Coach — Backend           ║
╠═══════════════════════════════════════════╣
║  URL:          http://localhost:5001      ║
║  DATABASE_URL: {db_status:<27}║
║  GEMINI_API_KEY: {key_status:<25}║
╚═══════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=5001, debug=True)