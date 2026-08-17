"""Rattache les compétences en texte libre (Gemini) à la taxonomie ESCO.

Sert deux usages, tous deux internes (jamais affichés à la place du texte
libre extrait par Gemini — voir profile_engine) :
1. Dédup/normalisation : deux libellés proches ("Python" / "python (avancé)")
   pointent vers le même esco_uri, ce qui permet le gap-analysis en (3).
2. get_priority_skills (profile_engine) : matcher l'objectif de carrière
   déclaré vers un métier ESCO, et comparer ses compétences essentielles à
   l'arbre de l'étudiant.

Matching 100% local (rapidfuzz contre les prefLabel/altLabels ESCO en
français) — aucun appel Gemini/IA ici, contrainte de coût explicite. Les CSV
sous data/esco/ sont un export trimmé (FR uniquement) de l'API publique ESCO
(https://ec.europa.eu/esco/api), voir data/esco/README.md pour la provenance.

Index construit une fois à l'import du module (données statiques, jamais
réécrites au runtime) — un seul worker gunicorn (voir Procfile), donc un seul
index en mémoire, pas de round-trip Postgres par lookup.
"""

import csv
import re
from pathlib import Path

from rapidfuzz import fuzz, process

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "esco"

# Matching interne (dédup) : score minimal pour accepter un match. Un match
# raté ici ne fait que rater une dédup — pas de risque d'afficher un mauvais
# libellé (le nom affiché reste toujours le texte brut de Gemini).
SKILL_MATCH_THRESHOLD = 88.0

# Matching user-visible ("3 compétences clés") : barre plus stricte, + écart
# minimal entre le 1er et le 2e candidat pour éviter un match ambigu — ici un
# mauvais match serait vu par l'étudiant, donc on préfère ne rien afficher.
OCCUPATION_MATCH_THRESHOLD = 80.0
OCCUPATION_AMBIGUITY_GAP = 8.0
# Au-dessus de cette barre, le match est accepté même si un métier voisin
# (ex: plusieurs variantes de "développeur d'applications X") suit de près —
# ESCO a énormément de métiers proches les uns des autres, donc un écart
# top1/top2 faible ne veut pas dire "ambigu" quand top1 est déjà très haut.
# En dessous, seuls des matchs avec un net écart au 2e sont acceptés (voir
# OCCUPATION_AMBIGUITY_GAP) — les objectifs vagues plafonnent nettement plus
# bas que ça avec plusieurs candidats non liés au coude à coude.
OCCUPATION_HIGH_CONFIDENCE = 90.0

_SKILL_META: dict[str, dict] = {}          # uri -> {"uri", "pref_label"}
_SKILL_CANDIDATES: dict[str, str] = {}     # libellé normalisé (pref ou alt) -> uri

_OCCUPATION_META: dict[str, dict] = {}
_OCCUPATION_CANDIDATES: dict[str, str] = {}

_ESSENTIAL_SKILLS_BY_OCCUPATION: dict[str, list[str]] = {}  # occupation_uri -> [skill_uri, ...]


_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _normalize(text: str) -> str:
    """Lowercase + espaces. Utilisé pour indexer les libellés ESCO eux-mêmes —
    on garde leurs parenthèses (souvent disambiguïsantes dans ESCO, ex:
    "Python (programmation informatique)" vs. un autre concept homonyme)."""
    return " ".join((text or "").strip().lower().split())


def _normalize_query(text: str) -> str:
    """Comme _normalize, plus le retrait d'un qualificatif final entre
    parenthèses (ex: "Python (avancé)" -> "python") — très courant sur les CV
    français ("(débutant)", "(confirmé)"...) et sans lien avec les parenthèses
    disambiguïsantes d'ESCO. Seulement appliqué au texte libre entrant, jamais
    aux libellés ESCO indexés (voir _normalize)."""
    cleaned = _TRAILING_PAREN_RE.sub("", (text or "").strip())
    return _normalize(cleaned)


def _load_skills() -> None:
    path = DATA_DIR / "skills_fr.csv"
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            uri = row["conceptUri"]
            pref = row["preferredLabel"]
            if not uri or not pref:
                continue
            _SKILL_META[uri] = {"uri": uri, "pref_label": pref}
            _SKILL_CANDIDATES[_normalize(pref)] = uri
            for alt in (row.get("altLabels") or "").split("|"):
                alt = alt.strip()
                if alt:
                    _SKILL_CANDIDATES.setdefault(_normalize(alt), uri)


def _load_occupations() -> None:
    path = DATA_DIR / "occupations_fr.csv"
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            uri = row["conceptUri"]
            pref = row["preferredLabel"]
            if not uri or not pref:
                continue
            _OCCUPATION_META[uri] = {"uri": uri, "pref_label": pref}
            _OCCUPATION_CANDIDATES[_normalize(pref)] = uri
            for alt in (row.get("altLabels") or "").split("|"):
                alt = alt.strip()
                if alt:
                    _OCCUPATION_CANDIDATES.setdefault(_normalize(alt), uri)


def _load_relations() -> None:
    path = DATA_DIR / "occupation_skill_relations_fr.csv"
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("relationType") != "essential":
                continue
            occ_uri = row["occupationUri"]
            skill_uri = row["skillUri"]
            if occ_uri in _OCCUPATION_META and skill_uri in _SKILL_META:
                _ESSENTIAL_SKILLS_BY_OCCUPATION.setdefault(occ_uri, []).append(skill_uri)


def _load_index() -> None:
    if _SKILL_META:  # déjà chargé
        return
    _load_skills()
    _load_occupations()
    _load_relations()


def match_skill(raw_name: str) -> dict | None:
    """{"uri", "pref_label", "score"} ou None si aucun match assez confiant."""
    query = _normalize_query(raw_name)
    if not query or not _SKILL_CANDIDATES:
        return None
    result = process.extractOne(query, _SKILL_CANDIDATES.keys(), scorer=fuzz.WRatio,
                                 score_cutoff=SKILL_MATCH_THRESHOLD)
    if not result:
        return None
    label, score, _ = result
    uri = _SKILL_CANDIDATES[label]
    return {**_SKILL_META[uri], "score": score}


def match_occupation(free_text: str) -> dict | None:
    """Comme match_skill, avec un seuil plus strict et une exigence d'écart
    top1/top2 (évite de forcer un match ambigu sur un objectif vague).

    L'écart top1/top2 se compare entre MÉTIERS distincts, pas entre libellés
    bruts : en français, un même métier a souvent plusieurs variantes genrées
    ("chargé de comptabilité" / "chargée de comptabilité") qui scorent à
    l'identique — comparer les libellés bruts déclencherait à tort le garde-fou
    anti-ambiguïté sur un match par ailleurs très confiant.
    """
    query = _normalize_query(free_text)
    if not query or not _OCCUPATION_CANDIDATES:
        return None
    # limit=8 : large marge pour que plusieurs variantes genrées/synonymes du
    # même métier n'empêchent pas d'atteindre un 2e métier RÉELLEMENT distinct.
    results = process.extract(query, _OCCUPATION_CANDIDATES.keys(), scorer=fuzz.WRatio,
                               score_cutoff=OCCUPATION_MATCH_THRESHOLD, limit=8)
    if not results:
        return None

    best_score_by_uri: dict[str, float] = {}
    for label, score, _ in results:
        uri = _OCCUPATION_CANDIDATES[label]
        if score > best_score_by_uri.get(uri, -1):
            best_score_by_uri[uri] = score
    ranked = sorted(best_score_by_uri.items(), key=lambda kv: -kv[1])

    uri, score = ranked[0]
    if score < OCCUPATION_HIGH_CONFIDENCE:
        if len(ranked) > 1 and (score - ranked[1][1]) < OCCUPATION_AMBIGUITY_GAP:
            return None
    return {**_OCCUPATION_META[uri], "score": score}


def get_essential_skills_for_occupation(occupation_uri: str) -> list[dict]:
    return [_SKILL_META[uri] for uri in _ESSENTIAL_SKILLS_BY_OCCUPATION.get(occupation_uri, [])]


_load_index()
