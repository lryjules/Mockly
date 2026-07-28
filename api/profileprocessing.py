"""
Analyse d'une fiche de poste : en extrait l'intitulé et la liste des
compétences clés à évaluer pendant l'entretien audio.
"""

from api import ai_gateway

FALLBACK_COMPETENCIES = [
    "Compétences techniques du poste",
    "Expérience professionnelle pertinente",
    "Travail d'équipe",
    "Résolution de problèmes",
    "Motivation pour le poste",
]


def analyze_job_posting(job_description: str, cv_data: dict | None = None) -> dict:
    """Extrait l'intitulé du poste et 4 à 6 compétences clés à évaluer à l'oral."""
    cv_context = ""
    if cv_data:
        competences = ", ".join(cv_data.get("competences", [])[:8])
        cv_context = f"\nProfil du candidat (CV) : compétences déjà mentionnées = {competences or 'non renseignées'}."

    prompt = f"""
Tu es un expert RH. Voici une fiche de poste :

\"\"\"{job_description}\"\"\"
{cv_context}

Analyse cette fiche de poste et renvoie un JSON avec :
- "job_title": l'intitulé du poste (court)
- "competencies": une liste de 4 à 6 compétences ou aptitudes clés (courtes, 2-5 mots chacune)
  que ce poste requiert et qu'il faut évaluer lors d'un entretien oral. Priorise les compétences
  les plus spécifiques et discriminantes pour ce poste précis (technique, métier, soft skills).

Réponds uniquement avec le JSON, sans texte autour.
"""
    fallback = {
        "job_title": job_description.strip().splitlines()[0][:80] if job_description.strip() else "Poste",
        "competencies": FALLBACK_COMPETENCIES,
    }

    result = ai_gateway.ai_call(prompt, fallback)

    competencies = result.get("competencies") or FALLBACK_COMPETENCIES
    return {
        "job_title": result.get("job_title") or fallback["job_title"],
        "competencies": [c.strip() for c in competencies if c and c.strip()][:6],
    }
