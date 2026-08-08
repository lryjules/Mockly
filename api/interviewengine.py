"""
Moteur de l'entretien audio : choisit la compétence à évaluer, génère la
question orale correspondante, puis produit l'évaluation écrite finale
une fois toutes les compétences couvertes.
"""

from api import ai_gateway


def pick_next_competency(all_competencies: list[str], covered_competencies: list[str]) -> str | None:
    """Renvoie la prochaine compétence non encore évaluée, ou None si tout a été couvert."""
    covered = set(covered_competencies)
    for competency in all_competencies:
        if competency not in covered:
            return competency
    return None


def generate_question(job_title: str, job_description: str, competency: str,
                       previous_questions: list[str], cv_data: dict | None = None,
                       interview_id: str | None = None, user_id: str | None = None) -> str:
    """Génère une question orale ciblant une compétence précise, sans répéter les précédentes."""
    cv_context = ""
    if cv_data:
        competences = ", ".join(cv_data.get("competences", [])[:8])
        cv_context = f"\nProfil du candidat (CV) : {competences or 'non renseigné'}."

    previous_text = "\n".join(f"- {q}" for q in previous_questions) or "Aucune"

    prompt = f"""
Tu es un recruteur qui mène un entretien d'embauche ORAL pour le poste "{job_title}".

Fiche de poste :
\"\"\"{job_description}\"\"\"
{cv_context}

Questions déjà posées dans cet entretien :
{previous_text}

Pose UNE SEULE question, naturelle et conversationnelle, pour évaluer chez le candidat la
compétence suivante : "{competency}".
Contraintes :
- Formule-la comme si tu parlais directement au candidat à l'oral (pas de style écrit/liste).
- Concise : 1 à 2 phrases maximum.
- Différente des questions déjà posées ci-dessus.

Réponds uniquement avec un JSON : {{"question": "..."}}
"""
    fallback = {"question": f"Pouvez-vous me parler d'une expérience qui illustre : {competency} ?"}
    result = ai_gateway.ai_call(prompt, fallback, context="interview_question",
                                 interview_id=interview_id, user_id=user_id)
    return result.get("question") or fallback["question"]


def _format_turns(turns: list[dict]) -> str:
    lines = []
    for i, turn in enumerate(turns, start=1):
        lines.append(
            f"{i}. Compétence évaluée : {turn.get('competency')}\n"
            f"   Question : {turn.get('question')}\n"
            f"   Réponse du candidat : {turn.get('user_response') or '(pas de réponse)'}"
        )
    return "\n".join(lines)


def generate_final_evaluation(job_title: str, job_description: str, turns: list[dict],
                                interview_id: str | None = None, user_id: str | None = None) -> dict:
    """Produit l'évaluation écrite globale de l'entretien, avec un score par compétence."""
    turns_text = _format_turns(turns)

    prompt = f"""
Tu es un recruteur expert. Voici le compte-rendu complet d'un entretien ORAL mené pour le poste
"{job_title}".

Fiche de poste :
\"\"\"{job_description}\"\"\"

Échanges de l'entretien :
{turns_text}

Rédige une évaluation globale de cet entretien. Réponds uniquement avec un JSON :
{{
  "score_global": <note entière sur 10>,
  "resume": "<résumé de la performance globale en 2-3 phrases>",
  "par_competence": [
    {{"competence": "...", "score": <sur 10>, "commentaire": "..."}}
  ],
  "points_forts": ["...", "..."],
  "ameliorations": ["...", "..."],
  "conseil_final": "<conseil actionnable pour la suite>"
}}
"""
    fallback = {
        "score_global": None,
        "resume": "Évaluation indisponible : configurez GEMINI_API_KEY pour activer l'analyse IA.",
        "par_competence": [
            {"competence": t.get("competency"), "score": None, "commentaire": "Non évalué (mode mock)."}
            for t in turns
        ],
        "points_forts": [],
        "ameliorations": [],
        "conseil_final": "",
    }
    return ai_gateway.ai_call(prompt, fallback, context="interview_eval",
                               interview_id=interview_id, user_id=user_id)
