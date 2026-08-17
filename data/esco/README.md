# Données ESCO (français)

Export trimmé de la taxonomie [ESCO](https://esco.ec.europa.eu/) (European
Skills, Competences, Qualifications and Occupations), licence **CC BY 4.0**.

- Libellés français (`preferredLabel`/`altLabels`) récupérés le 2026-08-17
  via l'API publique ESCO (`https://ec.europa.eu/esco/api/resource/skill` et
  `/resource/occupation`, endpoint bulk `?uris=...&language=fr`), version
  ESCO live au moment du fetch (~v1.2.1).
- La liste des URIs de concepts (skills/occupations) vient du mirror
  [tabiya-open-dataset](https://github.com/tabiya-tech/tabiya-open-dataset)
  (ESCO v1.1.1, CSV anglais) — utilisée uniquement pour obtenir la liste
  complète des URIs sans se heurter à la limite de pagination profonde de
  l'API de recherche ESCO (~200 résultats max sur `search?isInScheme=...`).
  Les libellés eux-mêmes viennent de l'API live, pas de ce mirror.

## Fichiers

- `skills_fr.csv` — `conceptUri, preferredLabel, altLabels` (altLabels séparés par `|`)
- `occupations_fr.csv` — même format, pour les métiers
- `occupation_skill_relations_fr.csv` — `occupationUri, skillUri, relationType`
  (`essential` ou `optional`)

## Régénérer

Script non commité (one-off, voir historique de session) : pagine
`/resource/{skill,occupation}?uris=...&language=fr` par lots de 50 URIs (au-delà,
l'API renvoie une réponse vide/HTTP 52), en s'appuyant sur la liste d'URIs du
mirror tabiya pour couvrir l'intégralité du référentiel.
