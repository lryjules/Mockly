"""Route de génération de sujets d'entretien : /api/generate-interview-topics."""

import json

from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api import ai_gateway
from api import token_budget
from api.user_helpers import get_informations_pro_for_session
from api.security import limiter, validate_length
from api.clerk_auth import require_auth, session_owned_by_current_user

topics_bp = Blueprint("topics", __name__)

ai_call = ai_gateway.ai_call

MAX_FIELD_LEN = 200


def generate_topics_with_ai(cv_data: dict, sector: str, company: str, role: str,
                             session_id: str | None = None, user_id: str | None = None) -> dict:
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
    return ai_call(prompt, context="topics_generation", session_id=session_id, user_id=user_id)


@topics_bp.route("/api/generate-interview-topics", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def generate_interview_topics():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    sector     = data.get("sector", "").strip()
    company    = (data.get("company", "") or "").strip()
    role       = (data.get("role", "") or "").strip()

    if not session_id or not sector:
        return jsonify({"error": "session_id et sector sont requis"}), 400
    for field_name, field_value in (("sector", sector), ("company", company), ("role", role)):
        if err := validate_length(field_value, field_name, MAX_FIELD_LEN):
            return err

    user_id = g.clerk_user_id
    if not token_budget.has_budget(user_id):
        return jsonify({"error": "Quota de tokens IA quotidien atteint. Réessaie demain, ou contacte ton établissement pour l'augmenter."}), 402

    with get_db() as conn:
        if not session_owned_by_current_user(conn, session_id):
            return jsonify({"error": "Session introuvable"}), 404
        row = conn.execute("SELECT cv_data FROM sessions WHERE id=%s", (session_id,)).fetchone()

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

    try:
        topics = generate_topics_with_ai(cv_data, sector, company, role, session_id=session_id, user_id=user_id)
    except ai_gateway.AIError as e:
        return jsonify({"error": str(e)}), 502

    with get_db() as conn:
        conn.execute(
            "INSERT INTO generations (session_id, sector, company, role, topics) VALUES (%s,%s,%s,%s,%s)",
            (session_id, sector, company, role, json.dumps(topics))
        )

    return jsonify(topics)
