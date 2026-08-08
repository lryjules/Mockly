"""Routes de l'entretien audio : /api/interview/start, /respond, /finish.

Règle importante pour éviter un "database is locked" silencieux : chaque
appel IA (ai_gateway.ai_call / speech.stt.transcribe) journalise son coût/
latence via api.ai_logging, qui ouvre SA PROPRE connexion SQLite. Si cet
appel a lieu pendant qu'une connexion `with get_db() as conn:` de cette
route est déjà ouverte ET a déjà écrit (INSERT/UPDATE non commité), la
connexion de journalisation se bloque et ai_logging avale l'erreur en
silence (elle ne doit jamais faire échouer l'appel IA lui-même) — résultat :
aucune ligne dans ai_call_log, sans aucune erreur visible.
D'où la structure de chaque route ci-dessous : 1) lire, 2) appeler l'IA
(aucune connexion ouverte), 3) écrire (une seule connexion, courte).
"""

import uuid
import json
import base64

from flask import Blueprint, request, jsonify, g

from api.db import get_db
from api.speech import stt as speech_stt
from api.speech import tts as speech_tts
from api import profileprocessing
from api import interviewengine
from api import profile_engine
from api import token_budget
from api.security import limiter, validate_length
from api.clerk_auth import require_auth, get_or_create_local_user, session_owned_by_current_user

interview_bp = Blueprint("interview", __name__)

MAX_JOB_DESCRIPTION_LEN = 6000
MAX_AUDIO_SIZE = 12 * 1024 * 1024  # 12 Mo


def _row_to_turn_dict(row) -> dict:
    return {
        "turn_index": row["turn_index"],
        "competency": row["competency"],
        "question": row["question"],
        "user_response": row["user_response"],
        "asked_at": row["asked_at"],
    }


def _generate_lookahead(interview_id, job_title, job_description,
                         competency_names, existing_turns, cv_data, user_id=None):
    """Génère (sans rien écrire) la question suivante, si une compétence reste à couvrir."""
    covered = [t["competency"] for t in existing_turns]
    next_competency = interviewengine.pick_next_competency(competency_names, covered)
    if not next_competency:
        return None

    previous_questions = [t["question"] for t in existing_turns]
    question = interviewengine.generate_question(
        job_title, job_description, next_competency, previous_questions, cv_data,
        interview_id=interview_id, user_id=user_id
    )
    return {"turn_index": len(existing_turns), "competency": next_competency, "question": question}


@interview_bp.route("/api/interview/start", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def interview_start():
    data = request.get_json(force=True)
    user_id = g.clerk_user_id
    session_id = data.get("session_id")
    job_description = (data.get("job_description") or "").strip()

    if not job_description:
        return jsonify({"error": "job_description requis"}), 400
    if err := validate_length(job_description, "job_description", MAX_JOB_DESCRIPTION_LEN):
        return err
    get_or_create_local_user(user_id)
    if not token_budget.has_budget(user_id):
        return jsonify({"error": "Quota de tokens IA quotidien atteint. Réessaie demain, ou contacte ton établissement pour l'augmenter."}), 402

    cv_data = None
    if session_id:
        with get_db() as conn:
            if not session_owned_by_current_user(conn, session_id):
                return jsonify({"error": "Session introuvable"}), 404
            row = conn.execute("SELECT cv_data FROM sessions WHERE id=%s", (session_id,)).fetchone()
        if row and row["cv_data"]:
            cv_data = json.loads(row["cv_data"])

    # --- Appels IA (aucune connexion ouverte pendant ce temps) ---
    analysis = profileprocessing.analyze_job_posting(job_description, cv_data, user_id=user_id)
    job_title = analysis["job_title"]
    competencies = analysis["competencies"]  # [{"name", "category", "weight"}, ...]
    competency_names = [c["name"] for c in competencies]

    interview_id = str(uuid.uuid4())

    first_competency = competency_names[0]
    first_question = interviewengine.generate_question(
        job_title, job_description, first_competency, [], cv_data,
        interview_id=interview_id, user_id=user_id
    )
    first_turn = {"turn_index": 0, "competency": first_competency, "question": first_question}
    lookahead = _generate_lookahead(
        interview_id, job_title, job_description, competency_names, [first_turn], cv_data,
        user_id=user_id
    )

    # --- Écriture : une seule connexion courte, après tous les appels IA ---
    with get_db() as conn:
        conn.execute(
            """INSERT INTO job_interviews (id, user_id, session_id, job_title, job_description, competencies)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (interview_id, user_id, session_id, job_title, job_description,
             json.dumps(competencies, ensure_ascii=False))
        )
        conn.execute(
            """INSERT INTO job_interview_turns (interview_id, turn_index, competency, question, asked_at)
               VALUES (%s,%s,%s,%s, to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))""",
            (interview_id, 0, first_competency, first_question)
        )
        if lookahead:
            conn.execute(
                """INSERT INTO job_interview_turns (interview_id, turn_index, competency, question)
                   VALUES (%s,%s,%s,%s)""",
                (interview_id, lookahead["turn_index"], lookahead["competency"], lookahead["question"])
            )

    audio = speech_tts.synthesize(first_question)

    return jsonify({
        "interview_id": interview_id,
        "job_title": job_title,
        "total_competencies": len(competency_names),
        "turn_index": 0,
        "competency": first_competency,
        "question": first_question,
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "finished": False,
    })


@interview_bp.route("/api/interview/respond", methods=["POST"])
@require_auth
@limiter.limit("60 per hour")
def interview_respond():
    interview_id = request.form.get("interview_id")
    turn_index = request.form.get("turn_index", type=int)
    audio_file = request.files.get("audio")

    if not interview_id or turn_index is None or not audio_file:
        return jsonify({"error": "interview_id, turn_index et audio requis"}), 400

    audio_file.stream.seek(0, 2)
    audio_size = audio_file.stream.tell()
    audio_file.stream.seek(0)
    if audio_size > MAX_AUDIO_SIZE:
        return jsonify({"error": "Fichier audio trop volumineux (max 12 Mo)"}), 413
    if audio_size == 0:
        return jsonify({"error": "Fichier audio vide"}), 400

    user_id = g.clerk_user_id
    if not token_budget.has_budget(user_id):
        return jsonify({"error": "Quota de tokens IA quotidien atteint. Réessaie demain, ou contacte ton établissement pour l'augmenter."}), 402

    # --- Lecture seule : tout le contexte nécessaire ---
    with get_db() as conn:
        interview = conn.execute("SELECT * FROM job_interviews WHERE id=%s", (interview_id,)).fetchone()
        if not interview or (interview["user_id"] and interview["user_id"] != g.clerk_user_id):
            return jsonify({"error": "Entretien introuvable"}), 404

        current_turn = conn.execute(
            "SELECT * FROM job_interview_turns WHERE interview_id=%s AND turn_index=%s",
            (interview_id, turn_index)
        ).fetchone()
        if not current_turn:
            return jsonify({"error": "Tour d'entretien introuvable"}), 404

        all_turns = [
            _row_to_turn_dict(r) for r in conn.execute(
                "SELECT * FROM job_interview_turns WHERE interview_id=%s ORDER BY turn_index",
                (interview_id,)
            ).fetchall()
        ]

        cv_data = None
        if interview["session_id"]:
            session_row = conn.execute("SELECT cv_data FROM sessions WHERE id=%s", (interview["session_id"],)).fetchone()
            if session_row and session_row["cv_data"]:
                cv_data = json.loads(session_row["cv_data"])

    # --- Appels IA (aucune connexion ouverte pendant ce temps) ---
    mime_type = (audio_file.mimetype or "audio/webm").split(";")[0]
    transcript = speech_stt.transcribe(audio_file.read(), mime_type, interview_id=interview_id, user_id=user_id)

    next_turn = next((t for t in all_turns if t["turn_index"] == turn_index + 1), None)

    new_lookahead = None
    if next_turn:
        competencies = json.loads(interview["competencies"])
        competency_names = [c["name"] for c in competencies]
        turns_up_to_next = all_turns[:next_turn["turn_index"] + 1]
        new_lookahead = _generate_lookahead(
            interview_id, interview["job_title"], interview["job_description"],
            competency_names, turns_up_to_next, cv_data, user_id=user_id
        )

    # --- Écriture : une seule connexion courte, après tous les appels IA ---
    with get_db() as conn:
        conn.execute(
            "UPDATE job_interview_turns SET user_response=%s WHERE interview_id=%s AND turn_index=%s",
            (transcript, interview_id, turn_index)
        )
        if next_turn:
            conn.execute(
                "UPDATE job_interview_turns SET asked_at=to_char(now(), 'YYYY-MM-DD HH24:MI:SS') WHERE interview_id=%s AND turn_index=%s",
                (interview_id, next_turn["turn_index"])
            )
            if new_lookahead:
                conn.execute(
                    """INSERT INTO job_interview_turns (interview_id, turn_index, competency, question)
                       VALUES (%s,%s,%s,%s)""",
                    (interview_id, new_lookahead["turn_index"], new_lookahead["competency"], new_lookahead["question"])
                )

    if not next_turn:
        return jsonify({
            "competency": current_turn["competency"],
            "transcript": transcript,
            "finished": True,
        })

    audio = speech_tts.synthesize(next_turn["question"])

    return jsonify({
        "competency": current_turn["competency"],
        "transcript": transcript,
        "finished": False,
        "turn_index": next_turn["turn_index"],
        "next_competency": next_turn["competency"],
        "question": next_turn["question"],
        "audio_base64": base64.b64encode(audio).decode("ascii"),
    })


@interview_bp.route("/api/interview/finish", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def interview_finish():
    data = request.get_json(force=True)
    interview_id = data.get("interview_id")
    if not interview_id:
        return jsonify({"error": "interview_id requis"}), 400

    user_id = g.clerk_user_id
    if not token_budget.has_budget(user_id):
        return jsonify({"error": "Quota de tokens IA quotidien atteint. Réessaie demain, ou contacte ton établissement pour l'augmenter."}), 402

    # --- Lecture seule ---
    with get_db() as conn:
        interview = conn.execute("SELECT * FROM job_interviews WHERE id=%s", (interview_id,)).fetchone()
        if not interview or (interview["user_id"] and interview["user_id"] != g.clerk_user_id):
            return jsonify({"error": "Entretien introuvable"}), 404

        turns = [
            _row_to_turn_dict(r) for r in conn.execute(
                "SELECT * FROM job_interview_turns WHERE interview_id=%s AND asked_at IS NOT NULL ORDER BY turn_index",
                (interview_id,)
            ).fetchall()
        ]

    # --- Appel IA (aucune connexion ouverte pendant ce temps) ---
    evaluation = interviewengine.generate_final_evaluation(
        interview["job_title"], interview["job_description"], turns,
        interview_id=interview_id, user_id=user_id
    )

    # --- Écriture ---
    with get_db() as conn:
        conn.execute(
            "UPDATE job_interviews SET status='completed', completed_at=to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), final_evaluation=%s WHERE id=%s",
            (json.dumps(evaluation, ensure_ascii=False), interview_id)
        )

    # profile_engine ouvre sa propre connexion : appelé après que la
    # transaction ci-dessus soit déjà validée (with refermé).
    if interview["user_id"]:
        competencies = json.loads(interview["competencies"])
        competency_metadata = {
            c["name"]: {"category": c.get("category", "autre"), "weight": c.get("weight", 2)}
            for c in competencies
        }
        profile_engine.finalize_interview_session(
            interview["user_id"], interview_id, evaluation, competency_metadata
        )

    return jsonify({"evaluation": evaluation, "turns": turns, "job_title": interview["job_title"]})
