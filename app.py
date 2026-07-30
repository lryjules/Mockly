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
  pages_routes      → sert le frontend (/, /results, /interview, /configuration)
"""

from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from flask_cors import CORS

from api.db import init_db
from api import ai_gateway

from api.routes.auth_routes import auth_bp
from api.routes.cv_routes import cv_bp
from api.routes.topics_routes import topics_bp
from api.routes.chat_routes import chat_bp
from api.routes.interview_routes import interview_bp
from api.routes.profile_routes import profile_bp
from api.routes.sessions_routes import sessions_bp
from api.routes.pages_routes import pages_bp

app = Flask(__name__, static_folder=None)
CORS(app, origins=["*"])

app.register_blueprint(auth_bp)
app.register_blueprint(cv_bp)
app.register_blueprint(topics_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(interview_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(pages_bp)  # toujours en dernier : contient la route catch-all "/<path:path>"

# Doit s'exécuter à l'import du module, pas seulement sous __main__ : gunicorn
# (utilisé en prod, ex. sur Render) importe `app` sans jamais passer par le
# bloc __main__ ci-dessous, donc les tables ne seraient jamais créées sinon.
init_db()


if __name__ == "__main__":
    key_status = "✅ configurée" if ai_gateway.GEMINI_API_KEY else "❌ non configurée (mode mock)"
    print(f"""
╔═══════════════════════════════════════════╗
║       Interview Coach — Backend           ║
╠═══════════════════════════════════════════╣
║  URL:          http://localhost:5001      ║
║  DB:           data/interview_coach.db    ║
║  GEMINI_API_KEY: {key_status:<25}║
╚═══════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=5001, debug=True)