<H1>Mockly - L'assistant IA garant de votre réussite</H1>

## 🌳 Calcul des compétences (arbre de progression)

Mockly construit pour chaque étudiant un **arbre de compétences personnel**, alimenté automatiquement par trois sources : le CV déposé, les entretiens audio, et les échanges notés avec le Coach IA. Cette section détaille exactement comment il est calculé.

Le code vit dans `api/profile_engine.py` (le "moteur" — seul module qui lit/écrit cet arbre), avec deux modules qui l'alimentent : `api/profileprocessing.py` (analyse d'une fiche de poste) et `api/interviewengine.py` (génération des questions et de l'évaluation finale d'un entretien).

### Modèle de données

Deux tables SQLite :

- **`student_competency`** — une ligne par (étudiant, compétence) :
  | colonne | rôle |
  |---|---|
  | `name` | nom de la compétence (ex: "Requêtage SQL") |
  | `category` | `technique`, `métier`, `soft_skill`, ou `autre` |
  | `current_score` | score courant, sur **0–100** |
  | `evaluation_count` | nombre de fois où cette compétence a été réellement évaluée |
  | `declared` | `1` si mentionnée sur un CV/chat mais jamais testée, `0` sinon |

- **`competency_evaluation`** — historique brut : une ligne par évaluation individuelle (score, feedback, session d'origine), conservée pour audit même si `current_score` n'en garde qu'une moyenne glissante.

### 1. D'où viennent les compétences

Une compétence peut apparaître dans l'arbre de deux façons différentes, qui donnent des statuts différents :

**a) Déclarée (grisée, non testée)** — `seed_declared_competencies()`, appelée à chaque dépôt de CV (`/api/upload-cv`). Les compétences listées par l'IA dans le CV (`cv_data.competences`) sont ajoutées avec `declared=1`, `current_score=0`, `evaluation_count=0`. **Elles n'écrasent jamais** une compétence déjà connue — ça ne sert qu'à peupler l'arbre pour ce qui n'a encore jamais été rencontré.

**b) Extraite d'une fiche de poste** — `profileprocessing.analyze_job_posting()`, appelée au démarrage d'un entretien audio (`/api/interview/start`) et lors d'un aperçu de préparation (`/api/profile/readiness-check`). Un prompt Gemini analyse la fiche de poste et renvoie 4 à 6 compétences, chacune avec :
  - un **nom** court (2-5 mots),
  - une **catégorie** (`technique` / `métier` / `soft_skill`),
  - un **poids** de 1 à 3, qui indique à quel point la compétence est *discriminante et spécifique à ce poste précis* (3 = indispensable et rare, 1 = générique — ex. "motivation").

  Si l'IA renvoie moins de 4 compétences exploitables, la liste est complétée avec une liste de secours générique (`FALLBACK_COMPETENCIES`) pour ne jamais bloquer le flux.

### 2. Comment un score est calculé : la moyenne pondérée par récence

C'est le cœur du calcul, dans `update_profile_tree()`. Il est appelé à chaque fois qu'une compétence est **réellement évaluée** — c'est-à-dire dans deux cas :

- à la fin d'un **entretien audio** (`finalize_interview_session()`, une fois par compétence couverte pendant l'entretien, sur la base du `par_competence` renvoyé par l'évaluation finale — score sur 10, converti ×10 pour rester sur l'échelle 0–100 de l'arbre) ;
- après une **réponse notée dans le Coach chat** (`/api/evaluate-response`) — l'IA elle-même identifie *quelle* compétence la question ciblait (`competence_ciblee`) et sa catégorie, et son score /10 est converti de la même façon.

Pour chaque nouveau score reçu :

```python
if evaluation_count == 0:
    nouveau_score = score_de_cette_évaluation          # premier passage : pas d'historique à pondérer
else:
    nouveau_score = ancien_score * 0.6 + score_de_cette_évaluation * 0.4
```

C'est une moyenne pondérée exponentielle avec `RECENCY_WEIGHT = 0.4` : chaque nouvelle performance compte pour 40 % du score, l'historique cumulé pour 60 %. Concrètement :
- une compétence jamais testée avant prend directement le score de sa première évaluation ;
- ensuite, le score **évolue** vers chaque nouvelle performance sans jamais l'adopter à 100 %, ce qui lisse les évaluations exceptionnelles (très bonnes ou très mauvaises) tout en restant réactif aux progrès réels.

`evaluation_count` s'incrémente à chaque fois. Une compétence `declared=1` avec `evaluation_count=0` **bascule automatiquement en "confirmée"** dès sa première vraie évaluation — pas de statut à gérer manuellement.

### 3. Déclaré vs confirmé : ce que voit l'étudiant

La page **Ma progression** (`get_competency_tree()`) groupe les compétences par catégorie et calcule pour chacune :
- `confirmed = evaluation_count > 0` → utilisée côté front pour afficher une barre pleine (score réel) ou une barre grisée/hachurée ("Non évalué").
- Tri par catégorie : confirmées d'abord, puis par score décroissant.

### 4. Le score de préparation pour une offre précise

`compute_readiness_score(student_id, competencies)`, utilisé par l'aperçu **"Estimer ma préparation"** avant de démarrer un entretien :

1. Calcule un **score neutre** = moyenne des `current_score` de toutes les compétences *réellement évaluées* de l'étudiant (`get_student_average_score`) — `50.0` par défaut si l'étudiant n'a encore aucune évaluation.
2. Pour chaque compétence exigée par la fiche de poste :
   - si l'étudiant l'a déjà évaluée → utilise son `current_score` réel ;
   - sinon → lui attribue le **score neutre** (ni pénalisé, ni avantagé pour une compétence jamais testée).
3. Fait la moyenne pondérée par le **poids** (discriminance) de chaque compétence :
   `score_préparation = Σ(score × poids) / Σ(poids)`
4. Renvoie aussi la **couverture** = part des compétences de l'offre déjà réellement évaluées au moins une fois — un score de préparation élevé avec une couverture faible signifie "encourageant, mais peu de données réelles".

### ⚠️ À ne pas confondre : le score d'un entretien ≠ le score d'une compétence

Le tableau de bord admin affiche aussi un "Average score" et une "Score progression" (`api/admin_metrics.py`). Ce sont des métriques **différentes** : elles lisent `job_interviews.final_evaluation.score_global`, la note globale sur **10** attribuée par l'IA à un entretien entier (résumé, points forts, axes d'amélioration), pas les scores par compétence sur 100 de l'arbre. Les deux systèmes cohabitent mais ne partagent ni échelle, ni table, ni formule.
