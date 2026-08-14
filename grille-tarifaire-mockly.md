# Grille tarifaire — Mockly (B2B écoles / career centers)

**Positionnement retenu :** prix d'appel, volume — signer vite des premiers pilotes, ajuster ensuite avec des vraies données de vente.
**Unité :** prix par étudiant couvert / an.
**Lancement :** remise de lancement (pas gratuit), pas de palier gratuit permanent.

---

## 1. Ce que dit vraiment le coût unitaire

Avant de fixer un prix, un chiffre concret tiré de votre propre code (`api/ai_logging.py`, tarif Gemini Flash ~0,075 $/M tokens en entrée, 0,30 $/M en sortie) et des logs déjà en base :

- Une analyse de CV ≈ 2 100 tokens entrée + 1 800 sortie → environ **0,0007 $**.
- Un tour de question/réponse d'entretien (question + transcription audio + évaluation) : même à une estimation large, on reste sous **0,05-0,10 $** par entretien complet.
- Avec l'allocation par défaut actuelle (3 crédits Coach + 3 crédits Interview par compte), le coût IA marginal par étudiant tourne autour de **0,30 à 0,50 € / an** — négligeable.

**Conséquence directe pour le pricing** : le coût IA n'est pas la contrainte. Ce qui coûte réellement à ce stade, c'est le temps commercial et support de mise en place de chaque école, pas l'usage. D'où la nécessité d'un **plancher de facturation par contrat** (ci-dessous), pour ne pas signer une petite école à un prix qui ne couvre même pas le temps passé à l'onboarder — plutôt qu'un prix par étudiant qui descendrait à l'infini sur les petits volumes.

## 2. Grille par palier

| Palier | Taille établissement | Prix / étudiant / an | Plancher de facturation |
|---|---|---|---|
| Starter | < 500 étudiants | **12 €** | 3 000 € / an minimum (soit 250 étudiants même si moins sont réellement inscrits) |
| Croissance | 500 – 1 500 étudiants | **9 €** | — |
| Grand compte | 1 500 – 5 000 étudiants | **6 €** | Devis à partir de 5 000 étudiants |

Le plancher Starter garantit un ticket minimum même pour une petite école pilote, sans décourager les tout premiers signataires (une école de 200 étudiants paie 3 000 €, pas 2 400 €, mais reste dans une fourchette "signature rapide, pas de comité d'achat").

## 3. Ce qui est inclus par étudiant couvert

- 3 crédits Coach (analyse CV + carte mentale + chat coach illimité pour la session)
- 3 crédits Interview (entretiens audio complets avec rapport détaillé)
- Accès du career center au tableau de bord école (KPIs pool, compétences faibles, gestion des crédits)

**Add-on crédits** (pour un étudiant qui dépasse son forfait, ou une école qui veut plus de volume par étudiant sans changer de palier) : pack de 50 crédits Interview supplémentaires = **90 €** (soit 1,80 €/crédit), pack de 50 crédits Coach = **40 €** (soit 0,80 €/crédit). Marge confortable vu le coût IA quasi nul par crédit — ce sont des packs pensés pour être simples à vendre, pas pour être justes au centime.

## 4. Offre de lancement

Remise, pas de gratuité, pour garder une valeur perçue dès le premier contact :

- **-30 % sur la première année** pour les écoles signées avant [À COMPLÉTER : date limite, ex. fin septembre].
- Prix plein applicable dès le renouvellement (année 2), annoncé clairement dès le devis pour éviter l'effet tarif choc à N+1.
- Optionnel : verrouiller le prix remisé sur 2 ans en échange d'un engagement contractuel de 2 ans plutôt que 1 — à trancher selon votre appétence pour la trésorerie immédiate vs la flexibilité de renégocier vite.

Exemple concret : une école de 400 étudiants → 12 €/étudiant → 4 800 € en tarif plein, **3 360 € la première année** avec la remise de lancement (au-dessus du plancher de 3 000 €, donc le plancher ne s'applique pas ici).

## 5. Ce qu'il reste à trancher

- **Durée d'engagement minimum** (1 an semble le point de départ logique, calé sur le cycle scolaire — à confirmer).
- **Facturation** : en une fois à la signature, ou en 2-3 échéances sur l'année scolaire (les écoles préfèrent souvent étaler).
- **Date limite de l'offre de lancement** et nombre d'écoles pilotes visées (ex. les 5 ou 10 premières).
- Ces trois points sont nécessaires pour finaliser l'article 4 des CGV — je les ai intégrés avec des placeholders clairs.

## 6. Prochaine validation recommandée

Cette grille est une hypothèse de départ cohérente avec vos coûts réels et les prix constatés sur le marché adjacent (les offres institutionnelles de plateformes de prépa entretien restent en général non publiques, sur devis). Elle mérite d'être confrontée aux 2-3 premiers vrais appels de découverte avant d'être gravée dans les CGV : si les prospects réagissent que c'est trop cher ou au contraire ne posent jamais la question du prix, c'est un signal à ajuster vite plutôt qu'après 10 signatures.

**Sources utilisées pour le repère marché (recherche web) :**
- [Big Interview — Pricing Enterprise](https://www.biginterview.com/pricing/enterprise)
- [Big Interview — Pricing Personal](https://www.biginterview.com/pricing/personal)
- [JobTeaser — modèle career center financé par les recruteurs](https://corporate.jobteaser.com/fr/recruiters)
