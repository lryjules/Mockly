from dotenv import load_dotenv
load_dotenv()  # charge le fichier .env au démarrage

"""
Interview Coach - Flask Backend
Routes:
  POST /api/upload-cv              → Upload & analyze CV (PDF/DOCX)
  POST /api/generate-interview-topics → Generate topics for a sector/company/role
  POST /api/start-chat             → Initialize AI coach chat
  POST /api/chat                   → Send chat message
  POST /api/evaluate-response      → Evaluate user's answer
  GET  /api/sessions               → List all sessions (history viewer)
  GET  /api/sessions/<id>          → Get session detail
  GET  /api/informations-pro/<user_id> → Get a user's professional info
  POST /api/informations-pro       → Create/update a user's professional info
  POST /api/interview/start        → Start an audio interview from a job posting
  POST /api/interview/respond      → Submit a recorded audio answer, get the next question
  POST /api/interview/finish       → Get the final written evaluation for an interview
"""

import uuid
import json
import base64
import hashlib
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

import sqlite3
import re

from api import ai_gateway
from api.speech import stt as speech_stt
from api.speech import tts as speech_tts
from api import profileprocessing
from api import interviewengine

# ── PDF / DOCX parsing ──────────────────────────────────────────────────────
try:
    from pdfminer.high_level import extract_text as pdf_extract_text
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

try:
    from docx import Document as DocxDocument
    DOCX_SUPPORT = True
except ImportError:
    DOCX_SUPPORT = False

# ── Configuration ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH  = DATA_DIR / "interview_coach.db"
UPLOADS_DIR = DATA_DIR / "uploads"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(BASE_DIR / "frontend"), static_url_path="")
CORS(app, origins=["*"])


# ═══════════════════════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════════════════════

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    # Migration: the profile table used to be called user_profiles.
    with get_db() as conn:
        try:
            conn.execute("ALTER TABLE user_profiles RENAME TO informations_pro")
        except sqlite3.OperationalError:
            pass

    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Informations professionnelles recueillies sur l'utilisateur
        -- (onboarding à la création de compte + page Configuration du workspace)
        CREATE TABLE IF NOT EXISTS informations_pro (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT NOT NULL UNIQUE REFERENCES users(id),
            study_level   TEXT,
            target_domain TEXT,
            current_goal  TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Sessions: one row per CV upload
        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            user_id     TEXT REFERENCES users(id),
            cv_filename TEXT,
            cv_text     TEXT,
            cv_data     TEXT,   -- JSON blob from AI parsing
            analysis    TEXT    -- JSON blob from AI analysis
        );

        -- Mind-map generations (one per "Générer la carte mentale" click)
        CREATE TABLE IF NOT EXISTS generations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(id),
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            sector      TEXT,
            company     TEXT,
            role        TEXT,
            topics      TEXT    -- JSON blob
        );

        -- Chat messages
        CREATE TABLE IF NOT EXISTS chat_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(id),
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            role        TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content     TEXT NOT NULL
        );

        -- Evaluated responses (question + user answer + AI evaluation)
        CREATE TABLE IF NOT EXISTS evaluations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT NOT NULL REFERENCES sessions(id),
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            question        TEXT NOT NULL,
            user_response   TEXT NOT NULL,
            score           INTEGER,
            evaluation_json TEXT    -- full JSON blob from AI
        );

        -- Entretiens audio : un entretien par fiche de poste soumise
        CREATE TABLE IF NOT EXISTS job_interviews (
            id               TEXT PRIMARY KEY,
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at     TEXT,
            user_id          TEXT REFERENCES users(id),
            session_id       TEXT REFERENCES sessions(id),
            job_title        TEXT,
            job_description  TEXT NOT NULL,
            competencies     TEXT NOT NULL,  -- JSON: liste des compétences à évaluer
            status           TEXT NOT NULL DEFAULT 'in_progress',  -- in_progress | completed
            final_evaluation TEXT             -- JSON blob de l'évaluation finale
        );

        -- Tours de question/réponse d'un entretien audio
        CREATE TABLE IF NOT EXISTS job_interview_turns (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id  TEXT NOT NULL REFERENCES job_interviews(id),
            turn_index    INTEGER NOT NULL,
            competency    TEXT NOT NULL,
            question      TEXT NOT NULL,
            user_response TEXT,
            asked_at      TEXT,   -- renseigné une fois la question réellement présentée au candidat
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """)

    with get_db() as conn:
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

import re


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_informations_pro(user_id: str | None):
    if not user_id:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT study_level, target_domain, current_goal FROM informations_pro WHERE user_id=?",
            (user_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "study_level": row["study_level"],
        "target_domain": row["target_domain"],
        "current_goal": row["current_goal"],
    }


def get_informations_pro_for_session(session_id: str | None):
    if not session_id:
        return None
    with get_db() as conn:
        row = conn.execute("SELECT user_id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not row or not row["user_id"]:
        return None
    return get_informations_pro(row["user_id"])


ai_call = ai_gateway.ai_call


def extract_cv_text(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf" and PDF_SUPPORT:
        return pdf_extract_text(filepath) or ""
    elif ext == ".docx" and DOCX_SUPPORT:
        doc = DocxDocument(filepath)
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        # Fallback: try reading as plain text
        try:
            with open(filepath, "r", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""


def parse_cv_with_ai(cv_text: str) -> tuple[dict, dict]:
    """
    Returns (cv_data, analysis) where:
      cv_data  = {nom, email, telephone, competences, experiences, formations}
      analysis = {conseils_cv, questions_preparation, sujets_entretien:{secteurs, competences_clés}}
    """
    prompt = f"""
Tu es un expert RH. Analyse ce CV et réponds UNIQUEMENT en JSON valide, sans markdown.

CV:
{cv_text[:8000]}

Retourne exactement ce format JSON:
{{
  "cv_data": {{
    "nom": "...",
    "email": "...",
    "telephone": "...",
    "competences": ["...", "..."],
    "experiences": ["...", "..."],
    "formations": ["...", "..."]
  }},
  "analysis": {{
    "conseils_cv": [
      "Conseil 1",
      "Conseil 2",
      "Conseil 3",
      "Conseil 4",
      "Conseil 5"
    ],
    "questions_preparation": [
      "Question 1",
      "Question 2",
      "Question 3",
      "Question 4",
      "Question 5"
    ],
    "sujets_entretien": {{
      "secteurs": ["Secteur 1", "Secteur 2", "Secteur 3"],
      "competences_clés": ["Compétence 1", "Compétence 2", "Compétence 3"]
    }}
  }}
}}
"""
    fallback = {
        "cv_data": {
            "nom": "Candidat",
            "email": "email@exemple.com",
            "telephone": "",
            "competences": ["Python", "JavaScript", "SQL"],
            "experiences": ["Développeur logiciel"],
            "formations": ["Master Informatique"]
        },
        "analysis": {
            "conseils_cv": [
                "Quantifiez vos réalisations avec des chiffres",
                "Adaptez votre CV au poste visé",
                "Mettez en avant vos soft skills",
                "Soignez la mise en page",
                "Ajoutez un résumé de profil percutant"
            ],
            "questions_preparation": [
                "Parlez-moi de vous",
                "Quelles sont vos principales compétences ?",
                "Pourquoi ce poste vous intéresse-t-il ?",
                "Quels sont vos points forts ?",
                "Où vous voyez-vous dans 5 ans ?"
            ],
            "sujets_entretien": {
                "secteurs": ["Tech", "Finance", "Conseil"],
                "competences_clés": ["Communication", "Résolution de problèmes", "Travail en équipe"]
            }
        }
    }
    result = ai_call(prompt, fallback)
    cv_data   = result.get("cv_data", fallback["cv_data"])
    analysis  = result.get("analysis", fallback["analysis"])
    return cv_data, analysis


def generate_topics_with_ai(cv_data: dict, sector: str, company: str, role: str) -> dict:
    competences = ", ".join(cv_data.get("competences", [])[:10])
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
    return ai_call(prompt, fallback)


def evaluate_response_with_ai(cv_data: dict, question: str, user_response: str) -> dict:
    prompt = f"""
Tu es un coach RH expert. Évalue cette réponse d'entretien.

Profil candidat: {json.dumps(cv_data, ensure_ascii=False)}
Question: {question}
Réponse du candidat: {user_response}

Réponds UNIQUEMENT en JSON valide sans markdown:
{{
  "score": 7,
  "evaluation": "Évaluation générale en 2-3 phrases",
  "points_forts": ["Point fort 1", "Point fort 2"],
  "ameliorations": ["Amélioration 1", "Amélioration 2"],
  "exemple_ameliore": "Exemple de réponse améliorée...",
  "questions_suivantes": ["Question de suivi 1", "Question de suivi 2"]
}}
"""
    fallback = {
        "score": 7,
        "evaluation": "Bonne réponse globalement. Vous avez su structurer vos idées clairement.",
        "points_forts": ["Structure claire", "Exemples concrets"],
        "ameliorations": ["Quantifiez davantage vos résultats", "Montrez plus d'enthousiasme"],
        "exemple_ameliore": "Je pourrais aussi ajouter un exemple chiffré pour renforcer mon propos.",
        "questions_suivantes": [
            "Pouvez-vous développer un exemple spécifique ?",
            "Comment avez-vous géré les obstacles rencontrés ?"
        ]
    }
    return ai_call(prompt, fallback)


# ═══════════════════════════════════════════════════════════════════════════
#  ROUTES — API
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/upload-cv", methods=["POST"])
def upload_cv():
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier fourni"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Nom de fichier vide"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".docx"):
        return jsonify({"error": "Format non supporté. Utilisez PDF ou DOCX"}), 400

    session_id = str(uuid.uuid4())
    filename   = f"{session_id}{ext}"
    filepath   = str(UPLOADS_DIR / filename)
    file.save(filepath)

    # Extract text
    cv_text = extract_cv_text(filepath)
    if not cv_text.strip():
        cv_text = "[Texte non extractable — vérifiez que le PDF n'est pas une image scannée]"

    # AI analysis
    cv_data, analysis = parse_cv_with_ai(cv_text)

    user_id = request.form.get("user_id") or None

    # Persist to DB
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, cv_filename, cv_text, cv_data, analysis) VALUES (?,?,?,?,?,?)",
            (session_id, user_id, file.filename, cv_text, json.dumps(cv_data), json.dumps(analysis))
        )

    return jsonify({
        "session_id": session_id,
        "cv_data":    cv_data,
        "analysis":   analysis
    })


@app.route("/api/generate-interview-topics", methods=["POST"])
def generate_interview_topics():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    sector     = data.get("sector", "").strip()
    company    = data.get("company", "") or ""
    role       = data.get("role", "") or ""

    if not session_id or not sector:
        return jsonify({"error": "session_id et sector sont requis"}), 400

    # Load session
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

    topics  = generate_topics_with_ai(cv_data, sector, company, role)

    # Save generation
    with get_db() as conn:
        conn.execute(
            "INSERT INTO generations (session_id, sector, company, role, topics) VALUES (?,?,?,?,?)",
            (session_id, sector, company, role, json.dumps(topics))
        )

    return jsonify(topics)


@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    confirm_password = (data.get("confirmPassword") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400
    if password != confirm_password:
        return jsonify({"error": "La confirmation du mot de passe ne correspond pas"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            return jsonify({"error": "Cet email est déjà utilisé"}), 409

        user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash) VALUES (?,?,?)",
            (user_id, email, hash_password(password))
        )
        conn.execute("INSERT INTO informations_pro (user_id) VALUES (?)", (user_id,))

    return jsonify({"message": "Compte créé", "user": {"id": user_id, "email": email}})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400

    with get_db() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email=?",
            (email,)
        ).fetchone()

    if not user or user["password_hash"] != hash_password(password):
        return jsonify({"error": "Identifiants invalides"}), 401

    profile = get_informations_pro(user["id"])
    return jsonify({
        "message": "Connexion réussie",
        "user": {"id": user["id"], "email": user["email"]},
        "profile": profile or {}
    })


@app.route("/api/informations-pro/<user_id>", methods=["GET"])
def get_informations_pro_route(user_id):
    profile = get_informations_pro(user_id)
    if profile is None:
        return jsonify({"error": "Profil introuvable"}), 404
    return jsonify({"profile": profile})


@app.route("/api/informations-pro", methods=["POST"])
def save_informations_pro():
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    study_level = (data.get("studyLevel") or "").strip()
    target_domain = (data.get("targetDomain") or "").strip()
    current_goal = (data.get("currentGoal") or "").strip()

    if not user_id:
        return jsonify({"error": "user_id requis"}), 400

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM informations_pro WHERE user_id=?", (user_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE informations_pro SET study_level=?, target_domain=?, current_goal=?, updated_at=datetime('now') WHERE user_id=?",
                (study_level, target_domain, current_goal, user_id)
            )
        else:
            conn.execute(
                "INSERT INTO informations_pro (user_id, study_level, target_domain, current_goal) VALUES (?,?,?,?)",
                (user_id, study_level, target_domain, current_goal)
            )

    return jsonify({"message": "Informations enregistrées", "profile": {
        "study_level": study_level,
        "target_domain": target_domain,
        "current_goal": current_goal,
    }})


@app.route("/api/start-chat", methods=["POST"])
def start_chat():
    data = request.get_json(force=True)
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id requis"}), 400

    with get_db() as conn:
        row = conn.execute(
            "SELECT cv_data, analysis FROM sessions WHERE id=?", (session_id,)
        ).fetchone()

    if not row:
        return jsonify({"error": "Session introuvable"}), 404

    cv_data  = json.loads(row["cv_data"])
    analysis = json.loads(row["analysis"])

    greeting = (
        f"Bonjour ! Je suis votre Coach IA pour préparer votre entretien. "
        f"J'ai analysé votre CV, {cv_data.get('nom', 'candidat')}. "
        f"Vous avez {len(cv_data.get('competences', []))} compétences identifiées. "
        f"Comment puis-je vous aider ?"
    )

    # Save greeting to DB
    with get_db() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (?,?,?)",
            (session_id, "assistant", greeting)
        )

    return jsonify({"message": greeting})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    message    = (data.get("message") or "").strip()

    if not session_id or not message:
        return jsonify({"error": "session_id et message requis"}), 400

    with get_db() as conn:
        session_row = conn.execute(
            "SELECT cv_data, analysis FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        history = conn.execute(
            "SELECT role, content FROM chat_messages WHERE session_id=? ORDER BY created_at",
            (session_id,)
        ).fetchall()

    if not session_row:
        return jsonify({"error": "Session introuvable"}), 404

    cv_data  = json.loads(session_row["cv_data"])
    analysis = json.loads(session_row["analysis"])

    # Build conversation context
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
            resp = ai_gateway.get_client().models.generate_content(
                model=ai_gateway.GEMINI_MODEL,
                contents=prompt
            )
            reply = resp.text.strip()
        except Exception as e:
            print(f"Chat AI error: {e}")
            reply = "Désolé, je rencontre une erreur momentanée. Pouvez-vous reformuler votre question ?"
    else:
        reply = (
            "Je suis votre coach IA ! Pour activer mes fonctionnalités complètes, "
            "configurez la variable d'environnement GEMINI_API_KEY."
        )

    # Save both messages to DB
    with get_db() as conn:
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (?,?,?)",
            (session_id, "user", message)
        )
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (?,?,?)",
            (session_id, "assistant", reply)
        )

    return jsonify({"message": reply})


@app.route("/api/evaluate-response", methods=["POST"])
def evaluate_response():
    data = request.get_json(force=True)
    session_id    = data.get("session_id")
    question      = (data.get("question") or "").strip()
    user_response = (data.get("response") or "").strip()

    if not session_id or not question or not user_response:
        return jsonify({"error": "session_id, question et response requis"}), 400

    with get_db() as conn:
        row = conn.execute("SELECT cv_data FROM sessions WHERE id=?", (session_id,)).fetchone()

    if not row:
        return jsonify({"error": "Session introuvable"}), 404

    cv_data    = json.loads(row["cv_data"])
    evaluation = evaluate_response_with_ai(cv_data, question, user_response)

    # Save to DB
    with get_db() as conn:
        conn.execute(
            """INSERT INTO evaluations
               (session_id, question, user_response, score, evaluation_json)
               VALUES (?,?,?,?,?)""",
            (
                session_id, question, user_response,
                evaluation.get("score"),
                json.dumps(evaluation, ensure_ascii=False)
            )
        )

    return jsonify(evaluation)


# ─── Audio interview endpoints ─────────────────────────────────────────────

def _row_to_turn_dict(row) -> dict:
    return {
        "turn_index": row["turn_index"],
        "competency": row["competency"],
        "question": row["question"],
        "user_response": row["user_response"],
        "asked_at": row["asked_at"],
    }


def _generate_and_store_lookahead(conn, interview_id, job_title, job_description,
                                   all_competencies, existing_turns, cv_data):
    """Génère et stocke (sans la présenter) la question suivante, si une compétence reste à couvrir."""
    covered = [t["competency"] for t in existing_turns]
    next_competency = interviewengine.pick_next_competency(all_competencies, covered)
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


@app.route("/api/interview/start", methods=["POST"])
def interview_start():
    data = request.get_json(force=True)
    user_id         = data.get("user_id")
    session_id      = data.get("session_id")
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
    competencies = analysis["competencies"]

    interview_id = str(uuid.uuid4())

    with get_db() as conn:
        conn.execute(
            """INSERT INTO job_interviews (id, user_id, session_id, job_title, job_description, competencies)
               VALUES (?,?,?,?,?,?)""",
            (interview_id, user_id, session_id, job_title, job_description, json.dumps(competencies, ensure_ascii=False))
        )

        first_competency = competencies[0]
        first_question = interviewengine.generate_question(job_title, job_description, first_competency, [], cv_data)
        conn.execute(
            """INSERT INTO job_interview_turns (interview_id, turn_index, competency, question, asked_at)
               VALUES (?,?,?,?, datetime('now'))""",
            (interview_id, 0, first_competency, first_question)
        )

        # Précharge la question suivante pendant que le candidat répond à la première.
        _generate_and_store_lookahead(
            conn, interview_id, job_title, job_description, competencies,
            [{"competency": first_competency, "question": first_question}], cv_data
        )

    audio = speech_tts.synthesize(first_question)

    return jsonify({
        "interview_id": interview_id,
        "job_title": job_title,
        "total_competencies": len(competencies),
        "turn_index": 0,
        "competency": first_competency,
        "question": first_question,
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "finished": False,
    })


@app.route("/api/interview/respond", methods=["POST"])
def interview_respond():
    interview_id = request.form.get("interview_id")
    turn_index   = request.form.get("turn_index", type=int)
    audio_file   = request.files.get("audio")

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
        _generate_and_store_lookahead(
            conn, interview_id, interview["job_title"], interview["job_description"],
            competencies, all_turns[:next_turn["turn_index"] + 1], cv_data
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


@app.route("/api/interview/finish", methods=["POST"])
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

    return jsonify({"evaluation": evaluation, "turns": turns, "job_title": interview["job_title"]})


# ─── History / results viewer endpoints ────────────────────────────────────

@app.route("/api/sessions", methods=["GET"])
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


@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    user_id = request.args.get("user_id")

    with get_db() as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
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


# ─── Serve frontend (results viewer) ───────────────────────────────────────

@app.route("/results")
def results_page():
    return send_from_directory(str(BASE_DIR / "frontend"), "results.html")


@app.route("/interview")
def interview_page():
    return send_from_directory(str(BASE_DIR / "frontend"), "interview.html")


@app.route("/configuration")
def configuration_page():
    return send_from_directory(str(BASE_DIR / "frontend"), "configuration.html")


@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR / "frontend"), "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(str(BASE_DIR / "frontend"), path)


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
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
