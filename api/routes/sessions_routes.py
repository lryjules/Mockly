"""Routes d'historique des sessions : /api/sessions, /api/sessions/<id>."""

import json

from flask import Blueprint, request, jsonify

from api.db import get_db

sessions_bp = Blueprint("sessions", __name__)


@sessions_bp.route("/api/sessions", methods=["GET"])
def list_sessions():
    # L'historique est individuel à chaque compte : sans user_id, personne ne voit de session.
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify([])

    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.id, s.created_at, s.cv_filename, s.cv_data,
                      COUNT(DISTINCT g.id)  AS nb_generations,
                      COUNT(DISTINCT cm.id) AS nb_messages,
                      COUNT(DISTINCT e.id)  AS nb_evaluations,
                      AVG(e.score)           AS avg_score
               FROM sessions s
               LEFT JOIN generations   g  ON g.session_id  = s.id
               LEFT JOIN chat_messages cm ON cm.session_id = s.id
               LEFT JOIN evaluations   e  ON e.session_id  = s.id
               WHERE s.user_id = ?
               GROUP BY s.id
               ORDER BY s.created_at DESC""",
            (user_id,)
        ).fetchall()

    result = []
    for r in rows:
        cv_data = json.loads(r["cv_data"]) if r["cv_data"] else {}
        result.append({
            "id":             r["id"],
            "created_at":     r["created_at"],
            "cv_filename":    r["cv_filename"],
            "candidate_name": cv_data.get("nom", "Inconnu"),
            "nb_generations": r["nb_generations"],
            "nb_messages":    r["nb_messages"],
            "nb_evaluations": r["nb_evaluations"],
            "avg_score":      round(r["avg_score"], 1) if r["avg_score"] else None
        })
    return jsonify(result)


@sessions_bp.route("/api/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    user_id = request.args.get("user_id")

    with get_db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            return jsonify({"error": "Session introuvable"}), 404
        if session["user_id"] and session["user_id"] != user_id:
            return jsonify({"error": "Session introuvable"}), 404

        generations = conn.execute(
            "SELECT * FROM generations WHERE session_id=? ORDER BY created_at DESC",
            (session_id,)
        ).fetchall()

        messages = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id=? ORDER BY created_at",
            (session_id,)
        ).fetchall()

        evaluations = conn.execute(
            "SELECT * FROM evaluations WHERE session_id=? ORDER BY created_at DESC",
            (session_id,)
        ).fetchall()

    def row_to_dict(row):
        return dict(row)

    return jsonify({
        "session":     row_to_dict(session),
        "generations": [row_to_dict(g) for g in generations],
        "messages":    [row_to_dict(m) for m in messages],
        "evaluations": [
            {**row_to_dict(e), "evaluation": json.loads(e["evaluation_json"]) if e["evaluation_json"] else {}}
            for e in evaluations
        ]
    })