"""
Analyse d'une fiche de poste : en extrait l'intitulé et la liste des
compétences clés à évaluer pendant l'entretien audio, chacune avec sa
catégorie et son poids discriminant (utilisés ensuite par profile_engine
pour construire l'arbre de compétences et le score de préparation).
"""
from api import ai_gateway

MAX_JOB_DESC_CHARS = 4000

FALLBACK_COMPETENCIES = [
    {"name": "Compétences techniques du poste", "category": "technique", "weight": 3},
    {"name": "Expérience professionnelle pertinente", "category": "métier", "weight": 2},
    {"name": "Travail d'équipe", "category": "soft_skill", "weight": 1},
    {"name": "Résolution de problèmes", "category": "soft_skill", "weight": 2},
    {"name": "Motivation pour le poste", "category": "soft_skill", "weight": 1},
]

VALID_CATEGORIES = {"technique", "métier", "soft_skill"}


def analyze_job_posting(job_description: str, cv_data: dict | None = None) -> dict:
    """Extrait l'intitulé du poste et 4 à 6 compétences clés à évaluer à l'oral.

    Renvoie : {"job_title": str, "competencies": [{"name", "category", "weight"}, ...]}
    """
    job_description = (job_description or "").strip()
    if not job_description:
        return {"job_title": "Poste", "competencies": FALLBACK_COMPETENCIES}

    # Tronque pour éviter un prompt disproportionné, et neutralise les guillemets
    # triples qui casseraient la structure du prompt.
    job_description = job_description[:MAX_JOB_DESC_CHARS].replace('"""', "'''")

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
- "competencies": une liste de 4 à 6 objets, chacun avec :
    - "name": la compétence ou aptitude clé (courte, 2-5 mots) à évaluer lors d'un entretien oral
    - "category": une valeur parmi "technique", "métier", "soft_skill"
    - "weight": un entier de 1 à 3 indiquant à quel point cette compétence est
      DISCRIMINANTE et spécifique à CE poste précis (3 = indispensable et rare,
      1 = générique/attendu pour n'importe quel poste, ex: "motivation")
Priorise les compétences les plus spécifiques et discriminantes pour ce poste précis.
Réponds uniquement avec le JSON, sans texte autour.
"""
    fallback = {
        "job_title": job_description.splitlines()[0][:80] if job_description else "Poste",
        "competencies": FALLBACK_COMPETENCIES,
    }

    try:
        result = ai_gateway.ai_call(prompt, fallback)
    except Exception:
        result = fallback

    raw_competencies = result.get("competencies") or FALLBACK_COMPETENCIES
    cleaned = []
    for c in raw_competencies:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        category = c.get("category")
        if category not in VALID_CATEGORIES:
            category = "autre"
        weight = c.get("weight")
        if weight not in (1, 2, 3):
            weight = 2
        cleaned.append({"name": name, "category": category, "weight": weight})
    cleaned = cleaned[:6]

    if len(cleaned) < 4:
        cleaned = (cleaned + FALLBACK_COMPETENCIES)[:6]

    return {
        "job_title": result.get("job_title") or fallback["job_title"],
        "competencies": cleaned,
    }