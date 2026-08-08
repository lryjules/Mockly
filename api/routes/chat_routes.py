"""Routes du coach chat : /api/start-chat, /api/chat, /api/evaluate-response."""

import json

from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api import ai_gateway
from api import ai_logging
from api import profile_engine
from api import token_budget
from api.security import limiter, validate_length
from api.clerk_auth import require_auth, session_owned_by_current_user

chat_bp = Blueprint("chat", __name__)

ai_call = ai_gateway.ai_call

VALID_CATEGORIES = {"technique", "métier", "soft_skill"}
MAX_MESSAGE_LEN = 4000
MAX_RESPONSE_LEN = 6000


def evaluate_response_with_ai(cv_data: dict, question: str, user_response: str,
                               session_id: str | None = None, user_id: str | None = None) -> dict:
    prompt = f"""
Tu es un coach RH expert. Évalue cette réponse d'entretien.

Profil candidat: {json.dumps(cv_data, ensure_ascii=False)}
Question: {question}
Réponse du candidat: {user_response}

Réponds UNIQUEMENT en JSON valide sans markdown:
{{
  "score": 7,
  "evaluation": "Évaluation générale en 2-3 phrases",
  "competence_ciblee": "Nom court de la compétence principale évaluée par cette question (2-5 mots)",
  "categorie": "technique, métier ou soft_skill",
  "points_forts": ["Point fort 1", "Point fort 2"],
  "ameliorations": ["Amélioration 1", "Amélioration 2"],
  "exemple_ameliore": "Exemple de réponse améliorée...",
  "questions_suivantes": ["Question de suivi 1", "Question de suivi 2"]
}}
"""
    fallback = {
        "score": 7,
        "evaluation": "Bonne réponse globalement. Vous avez su structurer vos idées clairement.",
        "competence_ciblee": "Communication",
        "categorie": "soft_skill",
        "points_forts": ["Structure claire", "Exemples concrets"],
        "ameliorations": ["Quantifiez davantage vos résultats", "Montrez plus d'enthousiasme"],
        "exemple_ameliore": "Je pourrais aussi ajouter un exemple chiffré pour renforcer mon propos.",
        "questions_suivantes": [
            "Pouvez-vous développer un exemple spécifique ?",
            "Comment avez-vous géré les obstacles rencontrés ?"
        ]
    }
    return ai_call(prompt, fallback, context="evaluate_response", session_id=session_id, user_id=user_id)


@chat_bp.route("/api/start-chat", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def start_chat():
    data = request.get_json(force=True)
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id requis"}), 400

    with get_db() as conn:
        if not session_owned_by_current_user(conn, session_id):
            return jsonify({"error": "Session introuvable"}), 404
        row = conn.execute("SELECT cv_data, analysis FROM sessions WHERE id=%s", (session_id,)).fetchone()

    if not row:
        return jsonify({"error": "Session introuvable"}), 404

    cv_data = json.loads(row["cv_data"])

    greeting = (
        f"Bonjour ! Je suis votre Coach IA pour préparer votre entretien. "
        f"J'ai analysé votre CV, {cv_data.get('nom', 'candidat')}. "
        f"Vous avez {len(cv_data.get('competences', []))} compétences identifiées. "
        f"Comment puis-je vous aider ?"
    )

    with get_db() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s,%s,%s)",
            (session_id, "assistant", greeting)
        )

    return jsonify({"message": greeting})


@chat_bp.route("/api/chat", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def chat():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    message = (data.get("message") or "").strip()

    if not session_id or not message:
        return jsonify({"error": "session_id et message requis"}), 400
    if err := validate_length(message, "message", MAX_MESSAGE_LEN):
        return err

    user_id = g.clerk_user_id
    if not token_budget.has_budget(user_id):
        return jsonify({"error": "Quota de tokens IA quotidien atteint. Réessaie demain, ou contacte ton établissement pour l'augmenter."}), 402

    with get_db() as conn:
        if not session_owned_by_current_user(conn, session_id):
            return jsonify({"error": "Session introuvable"}), 404
        session_row = conn.execute("SELECT cv_data, analysis FROM sessions WHERE id=%s", (session_id,)).fetchone()
        history = conn.execute(
            "SELECT role, content FROM chat_messages WHERE session_id=%s ORDER BY created_at",
            (session_id,)
        ).fetchall()

    if not session_row:
        return jsonify({"error": "Session introuvable"}), 404

    cv_data = json.loads(session_row["cv_data"])

    hist_text = "\n".join(f"[{r['role']}]: {r['content']}" for r in history[-10:])

    prompt = f"""
Tu es un coach RH expert en entretien d'embauche, bienveillant et professionnel.

Profil du candidat (CV analysé):
- Nom: {cv_data.get('nom','')}
- Compétences: {', '.join(cv_data.get('competences',[])[:8])}
- Expériences: {', '.join(cv_data.get('experiences',[])[:3])}

Historique récent du chat:
{hist_text}

Nouvelle question/message du candidat: {message}

Réponds en français, de façon concise (3-5 phrases max), comme un vrai coach bienveillant.
Ne renvoie que le texte de ta réponse, sans JSON.
"""
    if ai_gateway.get_client():
        try:
            with ai_logging.timed_call("chat", ai_gateway.GEMINI_MODEL, session_id=session_id, user_id=user_id) as record:
                resp = ai_gateway.get_client().models.generate_content(
                    model=ai_gateway.GEMINI_MODEL,
                    contents=prompt
                )
                record(resp.usage_metadata)
            reply = resp.text.strip()
        except Exception as e:
            print(f"Chat AI error: {e}")
            reply = "Désolé, je rencontre une erreur momentanée. Pouvez-vous reformuler votre question ?"
    else:
        reply = (
            "Je suis votre coach IA ! Pour activer mes fonctionnalités complètes, "
            "configurez la variable d'environnement GEMINI_API_KEY."
        )

    with get_db() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s,%s,%s)",
            (session_id, "user", message)
        )
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s,%s,%s)",
            (session_id, "assistant", reply)
        )

    return jsonify({"message": reply})


@chat_bp.route("/api/evaluate-response", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def evaluate_response():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    question = (data.get("question") or "").strip()
    user_response = (data.get("response") or "").strip()

    if not session_id or not question or not user_response:
        return jsonify({"error": "session_id, question et response requis"}), 400
    if err := validate_length(question, "question", MAX_MESSAGE_LEN):
        return err
    if err := validate_length(user_response, "response", MAX_RESPONSE_LEN):
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
    evaluation = evaluate_response_with_ai(cv_data, question, user_response, session_id=session_id, user_id=user_id)

    with get_db() as conn:
        conn.execute(
            """INSERT INTO evaluations
               (session_id, question, user_response, score, evaluation_json)
               VALUES (%s,%s,%s,%s,%s)""",
            (
                session_id, question, user_response,
                evaluation.get("score"),
                json.dumps(evaluation, ensure_ascii=False)
            )
        )
        session_row = conn.execute("SELECT user_id FROM sessions WHERE id=%s", (session_id,)).fetchone()

    # Branche cette évaluation sur l'arbre de compétences de l'étudiant, si connecté.
    competence = (evaluation.get("competence_ciblee") or "").strip()
    if session_row and session_row["user_id"] and competence:
        categorie = (evaluation.get("categorie") or "").strip().lower().replace(" ", "_")
        if categorie not in VALID_CATEGORIES:
            categorie = "autre"
        score = evaluation.get("score")
        if score is not None:
            profile_engine.update_profile_tree(
                session_row["user_id"], session_id,
                {competence: score * 10},
                {competence: categorie},
                {competence: evaluation.get("evaluation", "")},
            )

    return jsonify(evaluation)