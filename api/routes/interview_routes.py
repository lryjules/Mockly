"""Routes de l'entretien audio : /api/interview/start, /respond, /finish."""

import uuid
import json
import base64

from flask import Blueprint, request, jsonify

from api.db import get_db
from api.speech import stt as speech_stt
from api.speech import tts as speech_tts
from api import profileprocessing
from api import interviewengine
from api import profile_engine

interview_bp = Blueprint("interview", __name__)


def _row_to_turn_dict(row) -> dict:
    return {
        "turn_index": row["turn_index"],
        "competency": row["competency"],
        "question": row["question"],
        "user_response": row["user_response"],
        "asked_at": row["asked_at"],
    }


def _generate_and_store_lookahead(conn, interview_id, job_title, job_description,
                                   competency_names, existing_turns, cv_data):
    """Génère et stocke (sans la présenter) la question suivante, si une compétence reste à couvrir."""
    covered = [t["competency"] for t in existing_turns]
    next_competency = interviewengine.pick_next_competency(competency_names, covered)
    if not next_competency:
        return None

    previous_questions = [t["question"] for t in existing_turns]
    question = interviewengine.generate_question(
        job_title, job_description, next_competency, previous_questions, cv_data
    )
    next_index = len(existing_turns)
    conn.execute(
        """INSERT INTO job_interview_turns (interview_id, turn_index, competency, question)
           VALUES (?,?,?,?)""",
        (interview_id, next_index, next_competency, question)
    )
    return {"turn_index": next_index, "competency": next_competency, "question": question}


@interview_bp.route("/api/interview/start", methods=["POST"])
def interview_start():
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    job_description = (data.get("job_description") or "").strip()

    if not job_description:
        return jsonify({"error": "job_description requis"}), 400

    cv_data = None
    if session_id:
        with get_db() as conn:
            row = conn.execute("SELECT cv_data FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row and row["cv_data"]:
            cv_data = json.loads(row["cv_data"])

    analysis = profileprocessing.analyze_job_posting(job_description, cv_data)
    job_title = analysis["job_title"]
    competencies = analysis["competencies"]  # [{"name", "category", "weight"}, ...]
    competency_names = [c["name"] for c in competencies]

    interview_id = str(uuid.uuid4())

    with get_db() as conn:
        conn.execute(
            """INSERT INTO job_interviews (id, user_id, session_id, job_title, job_description, competencies)
               VALUES (?,?,?,?,?,?)""",
            (interview_id, user_id, session_id, job_title, job_description,
             json.dumps(competencies, ensure_ascii=False))
        )

        first_competency = competency_names[0]
        first_question = interviewengine.generate_question(job_title, job_description, first_competency, [], cv_data)
        conn.execute(
            """INSERT INTO job_interview_turns (interview_id, turn_index, competency, question, asked_at)
               VALUES (?,?,?,?, datetime('now'))""",
            (interview_id, 0, first_competency, first_question)
        )

        _generate_and_store_lookahead(
            conn, interview_id, job_title, job_description, competency_names,
            [{"competency": first_competency, "question": first_question}], cv_data
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
def interview_respond():
    interview_id = request.form.get("interview_id")
    turn_index = request.form.get("turn_index", type=int)
    audio_file = request.files.get("audio")

    if not interview_id or turn_index is None or not audio_file:
        return jsonify({"error": "interview_id, turn_index et audio requis"}), 400

    with get_db() as conn:
        interview = conn.execute("SELECT * FROM job_interviews WHERE id=?", (interview_id,)).fetchone()
        if not interview:
            return jsonify({"error": "Entretien introuvable"}), 404

        current_turn = conn.execute(
            "SELECT * FROM job_interview_turns WHERE interview_id=? AND turn_index=?",
            (interview_id, turn_index)
        ).fetchone()
        if not current_turn:
            return jsonify({"error": "Tour d'entretien introuvable"}), 404

        mime_type = (audio_file.mimetype or "audio/webm").split(";")[0]
        transcript = speech_stt.transcribe(audio_file.read(), mime_type)

        conn.execute(
            "UPDATE job_interview_turns SET user_response=? WHERE interview_id=? AND turn_index=?",
            (transcript, interview_id, turn_index)
        )

        all_turns = [
            _row_to_turn_dict(r) for r in conn.execute(
                "SELECT * FROM job_interview_turns WHERE interview_id=? ORDER BY turn_index",
                (interview_id,)
            ).fetchall()
        ]

        next_turn = next((t for t in all_turns if t["turn_index"] == turn_index + 1), None)
        if not next_turn:
            return jsonify({
                "competency": current_turn["competency"],
                "transcript": transcript,
                "finished": True,
            })

        conn.execute(
            "UPDATE job_interview_turns SET asked_at=datetime('now') WHERE interview_id=? AND turn_index=?",
            (interview_id, next_turn["turn_index"])
        )

        cv_data = None
        if interview["session_id"]:
            session_row = conn.execute("SELECT cv_data FROM sessions WHERE id=?", (interview["session_id"],)).fetchone()
            if session_row and session_row["cv_data"]:
                cv_data = json.loads(session_row["cv_data"])

        competencies = json.loads(interview["competencies"])
        competency_names = [c["name"] for c in competencies]
        _generate_and_store_lookahead(
            conn, interview_id, interview["job_title"], interview["job_description"],
            competency_names, all_turns[:next_turn["turn_index"] + 1], cv_data
        )

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
def interview_finish():
    data = request.get_json(force=True)
    interview_id = data.get("interview_id")
    if not interview_id:
        return jsonify({"error": "interview_id requis"}), 400

    with get_db() as conn:
        interview = conn.execute("SELECT * FROM job_interviews WHERE id=?", (interview_id,)).fetchone()
        if not interview:
            return jsonify({"error": "Entretien introuvable"}), 404

        turns = [
            _row_to_turn_dict(r) for r in conn.execute(
                "SELECT * FROM job_interview_turns WHERE interview_id=? AND asked_at IS NOT NULL ORDER BY turn_index",
                (interview_id,)
            ).fetchall()
        ]

        evaluation = interviewengine.generate_final_evaluation(
            interview["job_title"], interview["job_description"], turns
        )

        conn.execute(
            "UPDATE job_interviews SET status='completed', completed_at=datetime('now'), final_evaluation=? WHERE id=?",
            (json.dumps(evaluation, ensure_ascii=False), interview_id)
        )

    # Hors du `with` : profile_engine ouvre sa propre connexion, il faut que la
    # transaction ci-dessus soit déjà validée pour éviter un "database is locked".
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