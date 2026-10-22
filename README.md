# Analyseur de verbatims

Analyse automatique des réponses ouvertes d'enquêtes de satisfaction avec Claude : sentiment, thèmes et synthèse exécutive, en une minute et pour quelques francs CFA.

## Démo

- **URL publique** : _à compléter après le premier déploiement_
- **Capture du dashboard** : _à ajouter (`docs/dashboard.png`)_
- **Vidéo courte** : _à ajouter_
- **Maquettes** : dossier [`design/`](design/) (écrans, composants, variables de design)

## Le besoin

Une société d'études recueille pour ses clients des centaines de réponses libres (« Le réseau coupe tout le temps à Pikine… »). Les exploiter aujourd'hui, c'est :

- **lent** : un chargé d'études lit et code chaque réponse à la main, en créant sa grille de thèmes au fil de l'eau ;
- **coûteux** : plusieurs heures par enquête, à refaire à chaque vague ;
- **tardif** : la synthèse arrive quand le commanditaire a déjà besoin de décider.

## La solution

On dépose un fichier (CSV, Excel, Word, PDF, TXT ou JSON), on décrit l'enquête en une phrase, et l'outil rend en une à deux minutes : le sentiment de chaque réponse, une grille de 6 à 10 thèmes, des chiffres par thème et une synthèse d'une page prête à relire.

```
 Dashboard Angular ──── POST /api/analyses (CSV + contexte) ───▶ API FastAPI
       ▲                                                          │  tâche de fond
       └──────── GET /api/analyses/{id} toutes les 3 s ───────────┤  PostgreSQL
                                                                  ▼
             0. Prétraitement local (0 token) : vides, « RAS », doublons écartés
                + vérification du fichier → Claude Haiku 5.5 : est-ce bien une enquête ?
             1. Extraction par lots de 25    → Claude Haiku 5.5  : sentiment + thèmes
             2. Regroupement des thèmes      → Claude Sonnet 5.5 : grille finale
             3. Synthèse exécutive           → Claude Sonnet 5.5 : une page en Markdown
```

**Pourquoi ce découpage :**

- **Le modèle rapide et économique fait le volume.** Haiku traite les verbatims par lots de 25. Ses instructions, identiques d'un lot à l'autre, sont relues depuis le cache, ce qui les rend dix fois moins chères.
- **Le modèle plus fin ne voit que l'essentiel.** Sonnet reçoit seulement la liste des thèmes bruts pour construire la grille, puis seulement les chiffres agrégés et quelques citations pour la synthèse. Jamais l'ensemble des réponses.
- **Les thèmes restent cohérents sur toute l'enquête.** Chaque lot propose des libellés libres, puis une seule passe les regroupe. On évite ainsi « service client », « SAV » et « attente au 1234 » éparpillés en trois thèmes.
- **L'IA contrôle aussi ce qu'elle lit.** Un fichier qui n'est pas une enquête (contrat, article) est refusé avant toute dépense. Une réponse qui tente de manipuler l'IA (« ignore tes consignes… ») ou qui n'en est pas une (spam, publicité) est signalée et écartée des thèmes et de la synthèse. Les programmes, scripts et documents à macros sont refusés dès le dépôt.
- **Aucun chiffre ne vient du modèle.** Effectifs, pourcentages et répartitions sont recalculés localement. Le modèle ne renvoie jamais le texte des réponses, qui est déjà connu.

**Technologies** :

- Python 3.12, FastAPI, SQLModel et PostgreSQL 16, avec le SDK Anthropic ;
- Angular 21 (composants standalone, signals) et ng2-charts ;
- Docker, K3s et GitHub Actions.

## Le résultat

Mesures faites sur le jeu de démo : 223 réponses fictives d'une enquête télécom et mobile money au Sénégal, avec fautes, wolof, réponses vides et doublons. Il est décrit dans [`data/DATASET.md`](data/DATASET.md).

| Étape | Appels | Modèle | Tokens en entrée | Relus depuis le cache | Tokens en sortie | Coût |
|---|---:|---|---:|---:|---:|---:|
| Vérification du fichier | 1 | Haiku 5.5 | 1 721 | 0 | 112 | 0,0002 $ |
| Extraction | 9 | Haiku 5.5 | 10 225 | 36 126 | 12 002 | 0,007 $ |
| Regroupement | 1 | Sonnet 5.5 | 3 963 | 0 | 1 496 | 0,023 $ |
| Synthèse | 1 | Sonnet 5.5 | 3 458 | 0 | 884 | 0,016 $ |
| **Total** | **12** | | **19 367** | **36 126** | **14 494** | **0,046 $** |

**223 verbatims = 12 appels, environ 70 000 tokens, ~28 FCFA, en 79 secondes.** Sur quatre exécutions, le coût est resté entre 0,046 et 0,048 $ et la durée entre 64 et 93 s. Taux indicatif : 1 $ = 604 FCFA.

**Qualité, comparée à des étiquettes de référence posées à la création du jeu de données :**

- **Sentiment** : 95 % d'accord sur les 203 réponses analysées (96 % si l'on accepte « mixte » face à une polarité nette).
- **Bruit** : les 20 lignes parasites sur 20 sont écartées (10 réponses vides ou « RAS », 6 doublons exacts, 4 doublons ne différant que par des espaces), et chaque doublon pointe vers le bon original.
- **Sujets** : de 92 à 100 % des réponses sont rattachées au bon thème selon le sujet. La correspondance entre sujets et thèmes est écrite à la main dans [`data/samples/topic_mapping.json`](data/samples/topic_mapping.json).

**Thèmes obtenus**, triés par nombre de mentions : Forfaits et pass internet (26 %), Service client (24 %), Couverture réseau (22 %), Tarification mobile money (13 %), Accueil en agence (12 %), Application mobile (12 %), Appréciation générale (9 %), Services mobile money (9 %).

**Extrait de la synthèse générée :**

> **Points d'attention**
> - **Service client** (49 mentions, 24 %) : 59 % de retours négatifs et 20 % de mixtes, soit 79 % de retours critiques ou nuancés, sur la joignabilité et la communication en cas de panne : « Mettez plus d'agents au 1234 le week-end, c'est souvent occupé. »

## Lancer en local

**Prérequis** : PostgreSQL 16, [uv](https://github.com/astral-sh/uv), Node 24 et une clé API Anthropic.

```bash
# 1. Base de données (une fois)
createdb -U postgres sat_verbatim
createdb -U postgres sat_verbatim_test

# 2. Backend : http://localhost:8000/docs
cd backend
cp .env.example .env        # renseigner ANTHROPIC_API_KEY et le mot de passe PostgreSQL
uv sync
uv run uvicorn app.main:app --reload

# 3. Dashboard : http://localhost:4200
cd frontend
npm ci
npm start
```

Variante avec Docker pour le backend : `POSTGRES_PASSWORD=... docker compose up`.

**Fichiers acceptés** (5 Mo et 2 000 réponses maximum) :

- **Tableaux** (CSV, TSV, Excel `.xlsx`, tableau Word, JSON) : la colonne des réponses est détectée automatiquement. Une colonne nommée `verbatim`, `réponse`, `avis` ou `commentaire` est prise en priorité, sinon la colonne qui contient le plus de texte libre.
- **Textes** (TXT, Word `.docx`, PDF) : une réponse par ligne ou par paragraphe.
- **Refusés** : programmes, scripts (`.js`, `.html`…), documents à macros, PDF protégés, archives. Le format est vérifié sur le contenu du fichier, pas seulement sur son extension.

**Tests** : `cd backend && uv run pytest` (aucun appel réel à l'API, le modèle est simulé) et `cd frontend && npm run lint && npm run build`.

## Déploiement

1. Une seule image Docker ([`Dockerfile`](Dockerfile)) : le dashboard Angular est compilé puis servi par FastAPI.
2. **Avant le déploiement**, la CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) lance les tests du backend sur un PostgreSQL éphémère, puis le lint et le build du frontend, à chaque push.
3. **Le déploiement** ([`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)) se déclenche à chaque push sur `main`. Il construit l'image, la pousse sur GHCR avec le tag `sha-<commit>`, puis lance `kubectl set image` sur K3s.
4. Les manifests sont dans [`deploy/k8s/`](deploy/k8s/), namespace `sat` : un pod, un service, un ingress nginx et une sonde `/health`.
5. Les secrets sont créés à la main dans le cluster et ne sont jamais commités : `anthropic-api-key` et `database-url` (voir `secret.example.yaml`).
6. Un seul secret GitHub est nécessaire : `KUBECONFIG_B64`, le kubeconfig d'un compte limité au namespace `sat`.

## Limites et V2

- **Coût** : l'API Message Batches réduirait la facture de moitié pour les traitements non urgents.
- **Infrastructure** : l'analyse tourne dans le processus web. Une file de tâches serait nécessaire pour plusieurs utilisateurs simultanés.
- **Langues** : le jeu de démo est en français mêlé de wolof. D'autres langues ou des enquêtes très longues restent à tester.
- **Évaluation** : les étiquettes de référence ont été produites par le même type de modèle que l'outil. Une vraie validation demande une comparaison avec un codeur humain sur une enquête réelle.
- **Prévu en V1.1** : analyse à partir du lien d'une page publique (blog, forum, page d'avis d'une marque, en respectant les règles du site) et comparaison de plusieurs boutiques ou sources sur une grille de thèmes commune.
- **Fonctions absentes de la V1** : export CSV enrichi, suivi en temps réel sans rafraîchissement périodique, migrations de schéma de base de données, PDF scannés (pas de reconnaissance de caractères).
