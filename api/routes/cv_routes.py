"""Route d'upload et d'analyse de CV : /api/upload-cv."""

import uuid
import json
from pathlib import Path

from flask import Blueprint, request, jsonify, g

from api.db import get_db, UPLOADS_DIR
from api import ai_gateway
from api import profile_engine
from api import token_budget
from api.security import limiter
from api.clerk_auth import require_auth, get_or_create_local_user

MAX_CV_SIZE = 8 * 1024 * 1024  # 8 Mo

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

cv_bp = Blueprint("cv", __name__)

ai_call = ai_gateway.ai_call


def extract_cv_text(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf" and PDF_SUPPORT:
        return pdf_extract_text(filepath) or ""
    elif ext == ".docx" and DOCX_SUPPORT:
        doc = DocxDocument(filepath)
        return "\n".join(p.text for p in doc.paragraphs)
    else:
        try:
            with open(filepath, "r", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""


def parse_cv_with_ai(cv_text: str, user_id: str | None = None) -> tuple[dict, dict]:
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
    "conseils_cv": ["Conseil 1", "Conseil 2", "Conseil 3", "Conseil 4", "Conseil 5"],
    "questions_preparation": ["Question 1", "Question 2", "Question 3", "Question 4", "Question 5"],
    "sujets_entretien": {{
      "secteurs": ["Secteur 1", "Secteur 2", "Secteur 3"],
      "competences_clés": ["Compétence 1", "Compétence 2", "Compétence 3"]
    }}
  }}
}}
"""
    result = ai_call(prompt, context="cv_parse", user_id=user_id)
    cv_data = result.get("cv_data") or {}
    analysis = result.get("analysis") or {}
    return cv_data, analysis


@cv_bp.route("/api/upload-cv", methods=["POST"])
@require_auth
@limiter.limit("10 per hour")
def upload_cv():
    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier fourni"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Nom de fichier vide"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".docx"):
        return jsonify({"error": "Format non supporté. Utilisez PDF ou DOCX"}), 400

    file.stream.seek(0, 2)  # fin du flux
    size = file.stream.tell()
    file.stream.seek(0)
    if size > MAX_CV_SIZE:
        return jsonify({"error": "Fichier trop volumineux (max 8 Mo)"}), 413
    if size == 0:
        return jsonify({"error": "Fichier vide"}), 400

    user_id = g.clerk_user_id
    get_or_create_local_user(user_id)
    if not token_budget.has_budget(user_id):
        return jsonify({"error": "Quota de tokens IA quotidien atteint. Réessaie demain, ou contacte ton établissement pour l'augmenter."}), 402

    session_id = str(uuid.uuid4())
    filename = f"{session_id}{ext}"
    filepath = str(UPLOADS_DIR / filename)
    file.save(filepath)

    try:
        cv_text = extract_cv_text(filepath)
    except Exception as e:
        # Fichier corrompu, protégé par mot de passe, ou toute autre structure
        # que pdfminer/python-docx ne sait pas parser — pas une erreur serveur,
        # le fichier lui-même est en cause.
        print(f"[cv_routes] Extraction échouée pour {filepath}: {e}")
        return jsonify({"error": "Impossible de lire ce fichier. Il est peut-être corrompu, protégé par mot de passe, ou dans un format inattendu."}), 400
    if not cv_text.strip():
        cv_text = "[Texte non extractable — vérifiez que le PDF n'est pas une image scannée]"

    try:
        cv_data, analysis = parse_cv_with_ai(cv_text, user_id=user_id)
    except ai_gateway.AIError as e:
        return jsonify({"error": str(e)}), 502

    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, cv_filename, cv_text, cv_data, analysis) VALUES (%s,%s,%s,%s,%s,%s)",
            (session_id, user_id, file.filename, cv_text, json.dumps(cv_data), json.dumps(analysis))
        )

    # Alimente l'arbre de compétences avec les compétences déclarées du CV
    # (visibles côté front mais "grisées" tant qu'aucune évaluation réelle n'a eu lieu).
    if user_id:
        profile_engine.seed_declared_competencies(user_id, cv_data.get("competences", []))

    return jsonify({
        "session_id": session_id,
        "cv_data": cv_data,
        "analysis": analysis
    })