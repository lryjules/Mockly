"""Route de génération de sujets d'entretien : /api/generate-interview-topics."""

import json

from flask import Blueprint, request, jsonify

from api.db import get_db
from api import ai_gateway
from api.user_helpers import get_informations_pro_for_session

topics_bp = Blueprint("topics", __name__)

ai_call = ai_gateway.ai_call


def generate_topics_with_ai(cv_data: dict, sector: str, company: str, role: str,
                             session_id: str | None = None) -> dict:
    prompt = f"""
Tu es un expert RH spécialisé en entretiens. Génère des questions d'entretien ciblées.

Candidat: {json.dumps(cv_data, ensure_ascii=False)}
Secteur: {sector}
Entreprise: {company or 'Non spécifiée'}
Poste: {role or 'Non spécifié'}

Réponds UNIQUEMENT en JSON valide sans markdown:
{{
  "topics": {{
    "questions_culture_entreprise": [
      "Question sur la culture 1",
      "Question sur la culture 2",
      "Question sur la culture 3"
    ],
    "questions_job_specifiques": [
      "Question technique 1",
      "Question technique 2",
      "Question technique 3",
      "Question technique 4"
    ],
    "brain_teasers": [
      "Brain teaser 1",
      "Brain teaser 2"
    ]
  }}
}}
"""
    fallback = {
        "topics": {
            "questions_culture_entreprise": [
                f"Pourquoi souhaitez-vous rejoindre {company or 'cette entreprise'} ?",
                "Comment vous intégrez-vous dans une nouvelle équipe ?",
                "Quelle est votre philosophie de travail ?"
            ],
            "questions_job_specifiques": [
                f"Quelle est votre expérience dans le secteur {sector} ?",
                "Décrivez un projet dont vous êtes particulièrement fier.",
                f"Comment abordez-vous les défis techniques dans le domaine {sector} ?",
                "Quelle est votre méthode pour gérer les délais serrés ?"
            ],
            "brain_teasers": [
                "Si vous étiez un animal, lequel seriez-vous et pourquoi ?",
                "Comment vendriez-vous de la glace à un Esquimau ?"
            ]
        }
    }
    return ai_call(prompt, fallback, context="topics_generation", session_id=session_id)


@topics_bp.route("/api/generate-interview-topics", methods=["POST"])
def generate_interview_topics():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    sector     = data.get("sector", "").strip()
    company    = data.get("company", "") or ""
    role       = data.get("role", "") or ""

    if not session_id or not sector:
        return jsonify({"error": "session_id et sector sont requis"}), 400

    with get_db() as conn:
        row = conn.execute("SELECT cv_data FROM sessions WHERE id=?", (session_id,)).fetchone()

    if not row:
        return jsonify({"error": "Session introuvable"}), 404

    cv_data = json.loads(row["cv_data"])
    user_profile = get_informations_pro_for_session(session_id)
    profile_context = ""
    if user_profile:
        profile_context = (
            f"Profil utilisateur: niveau d'étude={user_profile.get('study_level') or 'non renseigné'}, "
            f"domaine={user_profile.get('target_domain') or 'non renseigné'}, "
            f"objectif={user_profile.get('current_goal') or 'non renseigné'}."
        )

    topics = generate_topics_with_ai(cv_data, sector, company, role, session_id=session_id)

    with get_db() as conn:
        conn.execute(
            "INSERT INTO generations (session_id, sector, company, role, topics) VALUES (?,?,?,?,?)",
            (session_id, sector, company, role, json.dumps(topics))
        )

    return jsonify(topics)
