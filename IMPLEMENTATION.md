# IMPLEMENTATION.md — Démonstrateur d'analyse automatique de verbatims (V1)

> Plan d'implémentation destiné à être exécuté avec Claude Code, phase par phase.
> Deadline V1 : **jeudi 23 octobre 2026, matin**. 4 sessions de 2-3h.
> Règle d'or : **une V1 finie vaut mieux qu'une V2 entamée.** Tout ce qui est marqué `[V2]` est hors périmètre.

---

## 0. Contexte

**Pour qui :** la SAT (Société d'Analyse et de Traitement), société d'études marketing. Leur besoin réel : exploiter automatiquement les réponses ouvertes des enquêtes de satisfaction qu'elle réalise pour ses clients.

**Ce que la V1 démontre :**
1. Sentiment par verbatim (positif / neutre / négatif / mixte)
2. Extraction de thèmes par verbatim, puis regroupement en thèmes canoniques au niveau de l'enquête
3. Synthèse exécutive rédigée (1 page) pour le commanditaire
4. Le tout exposé en API REST (FastAPI), consommé par un dashboard Angular, déployé sur K3s, CI/CD GitHub Actions

**Jeu de données de démo :** enquête de satisfaction fictive d'un opérateur télécom / mobile money au Sénégal, ~200 verbatims synthétiques en français avec bruit réaliste (fautes, mots wolof, « RAS », réponses vides, sarcasme, doublons). Le pipeline est agnostique au secteur : chaque analyse reçoit un champ `context` libre (« enquête post-achat, agence bancaire, Dakar, septembre 2026 »).

---

## 1. Architecture

```
┌──────────────┐   POST /api/analyses (CSV + context)   ┌────────────────────────┐
│  Angular SPA │ ─────────────────────────────────────▶ │  FastAPI               │
│  (dashboard) │ ◀───────── poll GET /api/analyses/{id} │  BackgroundTasks       │
└──────────────┘                                        │  PostgreSQL (SQLModel) │
                                                        │                        │
                                                        │  pipeline/             │
                                                        │   1. preprocess (local)│
                                                        │   2. extract  ──┐      │
                                                        │   3. cluster  ──┼─▶ Claude API
                                                        │   4. synthesize─┘      │
                                                        └────────────────────────┘
```

- **Un seul conteneur** : image multi-stage (build Angular → copie du `dist/` dans `backend/static/`, FastAPI sert la SPA avec fallback `index.html`). Un Deployment, un Service, un Ingress. Pas de second service à déployer la veille de la deadline.
- **Asynchrone sans infra supplémentaire** : `BackgroundTasks` de FastAPI + statut/progression persistés en PostgreSQL. Pas de Redis, pas de Celery `[V2]`.
- **PostgreSQL 16** : en local, l'instance déjà installée sur `localhost:5432` (bases `sat_verbatim` et `sat_verbatim_test`). Connexion via `DATABASE_URL` (driver `psycopg` v3). L'hébergement de Postgres en production est **à décider avant la session 4** (on construit et on teste tout en local d'abord).

---

## 2. Pipeline — conception optimisée tokens

Objectif : **minimum d'appels, minimum de tokens par appel, zéro texte renvoyé inutilement.**

### 2.1 Étape 0 — Prétraitement local (0 token)

Fait en Python, avant tout appel :
- Normalisation (trim, espaces multiples, casse des « RAS »/« ras »/« R.A.S »).
- **Filtrage** des verbatims vides ou non informatifs (`""`, `RAS`, `rien`, `aucun`, `.`, `-`, < 3 caractères) → marqués `skipped_reason = "empty"`, jamais envoyés.
- **Déduplication exacte** (hash du texte normalisé) → les doublons héritent du résultat du premier, `skipped_reason = "duplicate_of:<idx>"`.
- Troncature de sécurité à 600 caractères par verbatim (log si tronqué).
- Sur 200 verbatims synthétiques, attendre ~15-20 % de filtrés.

### 2.2 Étape 1 — Extraction par lot (`extract.py`)

- **Lots de 25 verbatims** par appel → ~7-8 appels pour 200 verbatims.
- Entrée compacte : une ligne par verbatim, `"{idx}: {texte}"`. Pas de JSON d'entrée (coûteux en tokens).
- **System prompt stable** (rôle, définitions des sentiments, règles de thèmes, 4-5 exemples few-shot) marqué `cache_control: {"type": "ephemeral"}`. Il est identique pour tous les lots → lu depuis le cache à partir du 2e appel. Le system prompt doit dépasser le seuil minimal de cache du modèle (viser > 2 000 tokens, les few-shot y aident).
- Le `context` de l'analyse va dans le **user message** (il change d'une analyse à l'autre), pas dans le system prompt.
- **Sortie forcée par tool use** (`tool_choice: {"type": "tool", "name": "record_extraction"}`, accepté par Haiku 5.5) avec schéma strict :
  ```json
  {
    "results": [
      {
        "idx": 12,
        "sentiment": "negative",          // enum: positive | neutral | negative | mixed
        "themes": ["délai d'activation", "service client injoignable"],  // 1 à 3, libellés courts, minuscules, en français
        "key_phrase": "3 jours sans réseau"   // ≤ 8 mots, extrait du verbatim, optionnel
      }
    ]
  }
  ```
  Le modèle **ne renvoie jamais le texte du verbatim** (on l'a déjà). Pas de champ « explication ». Pas de score de confiance en V1.
- `max_tokens` borné (~1 500 pour 25 verbatims), `effort: low`. **Pas de `temperature`** : Haiku 5.5 et Sonnet 5.5 rejettent toute valeur non par défaut (400). La stabilité vient du schéma strict et du prompt.
- Modèle : **`claude-haiku-5-5`** (volume, coût). Fallback configurable par variable d'env `EXTRACT_MODEL`.
- Validation post-appel : chaque `idx` du lot doit être présent ; les manquants sont relancés une fois dans un mini-lot, sinon `skipped_reason = "extraction_failed"`.
- Retry avec backoff exponentiel sur 429/529/5xx (3 tentatives). Le SDK Anthropic le fait nativement avec `max_retries`.

### 2.3 Étape 2 — Regroupement des thèmes (`cluster.py`)

- **Un seul appel.** Entrée : la liste des libellés de thèmes bruts **uniques avec leur fréquence**, triés par fréquence décroissante (`"service client injoignable (14)"`). Jamais les verbatims. Sur 200 verbatims on a typiquement 80-150 libellés bruts → ~1 000 tokens d'entrée.
- Sortie par tool use `record_theme_mapping` :
  ```json
  {
    "themes": [
      {
        "label": "Qualité du service client",
        "description": "Joignabilité, délais de réponse, compétence des agents",
        "raw_labels": ["service client injoignable", "agent incompétent", "attente au 1234"]
      }
    ]
  }
  ```
- Contrainte dans le prompt : **6 à 10 thèmes canoniques**, chaque libellé brut doit être affecté à exactement un thème, un thème « Autres » est autorisé mais doit rester < 10 % des occurrences.
- Vérification locale : tout libellé brut non mappé est rattaché à « Autres » (pas de second appel).
- Modèle : **`claude-sonnet-5-5`** (qualité du regroupement, un seul appel donc coût marginal). Sonnet 5.5 rejette le `tool_choice` forcé : `tool_choice: auto` + `strict: true` + consigne du prompt, puis vérification locale qu'un appel `record_theme_mapping` est bien revenu (un seul nouvel essai sinon). `effort: low`, `max_tokens` ~4 000 (la réflexion adaptative compte dans `max_tokens`).
- Après cette étape, on calcule **localement** : effectif par thème, répartition des sentiments par thème, verbatims représentatifs par thème (les 3 verbatims les plus courts contenant la `key_phrase` ou, à défaut, les 3 premiers).

### 2.4 Étape 3 — Synthèse exécutive (`synthesize.py`)

- **Un seul appel.** Entrée : le `context`, les statistiques agrégées (effectifs, % sentiments globaux, tableau thèmes × sentiments) et **2-3 verbatims représentatifs par thème, tronqués à 200 caractères**. Jamais l'ensemble des verbatims. ~2 000-3 000 tokens d'entrée.
- Sortie : Markdown structuré (texte libre, pas de tool use ici) :
  - Chiffres clés (3-4 lignes)
  - Points forts (2-3 puces, avec thème + chiffre)
  - Points d'attention (3-4 puces, priorisées)
  - Recommandations (3 puces actionnables)
- `max_tokens` ~3 000 (réflexion adaptative incluse), `effort: low`, pas de `temperature`, modèle **`claude-sonnet-5-5`**.

### 2.5 Comptabilité des tokens

- Chaque appel enregistre `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, modèle, durée, étape → table `llm_calls`.
- Le coût estimé est calculé à partir d'une grille de prix dans `config.py` (à mettre à jour depuis la doc Anthropic au moment du dev, ne pas inventer les chiffres).
- Exposé via `GET /api/analyses/{id}/usage` et affiché dans le dashboard. **C'est un argument de vente** pour la SAT : « 200 verbatims = X appels, Y tokens, ~Z FCFA, en N secondes ».

### 2.6 Cache de résultats

- Clé = SHA-256 du CSV normalisé + `context` + versions des prompts. Si une analyse identique existe déjà en base avec statut `done`, on renvoie son id au lieu de relancer (évite de brûler des tokens en répétant la démo).

### 2.7 Ordres de grandeur attendus (200 verbatims)

| Étape | Appels | Modèle | Tokens in (hors cache) | Tokens out |
|---|---|---|---|---|
| Extraction | 7-8 | Haiku | ~8 × 1 200 (+ system en cache) | ~8 × 800 |
| Regroupement | 1 | Sonnet | ~1 500 | ~600 |
| Synthèse | 1 | Sonnet | ~3 000 | ~900 |
| **Total** | **~10** | | **~15 k** | **~8 k** |

Durée attendue : 60-120 s. `[V2]` : Message Batches API (-50 % de coût) pour les traitements non interactifs.

---

## 3. Modèle de données (SQLModel)

```python
class Analysis:
    id: str                 # uuid4
    name: str
    context: str
    status: str             # pending | processing | done | failed
    progress: int           # 0-100
    current_step: str       # preprocess | extract | cluster | synthesize | done
    error: str | None
    content_hash: str
    stats: dict             # JSON: totals, sentiment distribution, theme table
    synthesis_md: str | None
    created_at, finished_at: datetime

class Verbatim:
    id: int
    analysis_id: str
    idx: int                # position in CSV
    text: str
    text_norm: str
    sentiment: str | None
    themes_raw: list[str]   # JSON
    key_phrase: str | None
    skipped_reason: str | None

class Theme:
    id: int
    analysis_id: str
    label: str
    description: str
    raw_labels: list[str]   # JSON
    count: int
    sentiment_breakdown: dict   # JSON {positive: n, ...}
    representative_idx: list[int]   # JSON

class VerbatimTheme:        # many-to-many
    verbatim_id, theme_id

class LlmCall:
    id, analysis_id, step, model, input_tokens, cache_creation_tokens,
    cache_read_tokens, output_tokens, duration_ms, created_at
```

---

## 4. Contrats d'API

Préfixe `/api`. Réponses JSON, erreurs au format `{"detail": "..."}`.

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/health` | Liveness + version |
| `POST` | `/api/analyses` | `multipart/form-data` : `file` (CSV, colonne `verbatim` obligatoire, `id` optionnelle), `name`, `context`. Retourne **202** `{id, status}` immédiatement. Lance la tâche de fond. |
| `GET` | `/api/analyses` | Liste `[{id, name, status, progress, created_at, total_verbatims}]` |
| `GET` | `/api/analyses/{id}` | Détail : statut, progression, `current_step`, `stats`, `synthesis_md`, `error` |
| `GET` | `/api/analyses/{id}/themes` | Thèmes canoniques avec effectifs, répartition des sentiments, verbatims représentatifs |
| `GET` | `/api/analyses/{id}/verbatims` | Paginé (`page`, `size`), filtres `sentiment`, `theme_id`, `q` (recherche texte), `include_skipped` |
| `GET` | `/api/analyses/{id}/usage` | Tokens par étape, coût estimé, durée |
| `GET` | `/api/analyses/{id}/export` | `[V2]` CSV enrichi |

Le dashboard **polle `GET /api/analyses/{id}` toutes les 3 s** tant que `status in (pending, processing)`. SSE/WebSocket `[V2]`.

---

## 5. Structure du repo

```
sat-verbatim-analyzer/
├── README.md                  # Besoin / Solution / Résultat (voir §8)
├── IMPLEMENTATION.md          # ce fichier
├── CLAUDE.md                  # conventions pour Claude Code
├── .github/workflows/
│   ├── ci.yml                 # lint + tests backend, build frontend (PR + push)
│   └── deploy.yml             # build image → GHCR → kubectl set image (push main)
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, routers, static SPA mount
│   │   ├── config.py          # Settings (pydantic-settings), model names, pricing table
│   │   ├── db.py              # engine, session, init
│   │   ├── models.py          # SQLModel tables
│   │   ├── schemas.py         # Pydantic I/O schemas
│   │   ├── api/
│   │   │   └── analyses.py    # routes
│   │   ├── services/
│   │   │   ├── analysis_service.py   # orchestration, status updates
│   │   │   └── csv_loader.py
│   │   └── pipeline/
│   │       ├── preprocess.py
│   │       ├── extract.py
│   │       ├── cluster.py
│   │       ├── synthesize.py
│   │       ├── llm_client.py  # Anthropic SDK wrapper, retries, usage logging
│   │       └── prompts/
│   │           ├── extract_system.md
│   │           ├── cluster_system.md
│   │           └── synthesize_system.md
│   ├── tests/
│   │   ├── test_preprocess.py
│   │   ├── test_pipeline_mocked.py   # LLM mocké, pas d'appel réseau
│   │   └── test_api.py
│   ├── scripts/
│   │   ├── generate_dataset.py       # génère data/samples/*.csv via Claude
│   │   └── run_pipeline_cli.py       # exécution hors API pour debug
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                  # Angular (dernière LTS), standalone components
│   └── src/app/
│       ├── core/              # api.service.ts, models.ts, polling
│       ├── pages/
│       │   ├── analyses-list/
│       │   ├── analysis-new/
│       │   └── analysis-detail/
│       └── shared/            # sentiment-badge, theme-card, usage-panel
├── data/samples/
│   └── telecom_satisfaction_200.csv
├── deploy/k8s/
│   ├── namespace.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── pvc.yaml
│   └── secret.example.yaml    # ANTHROPIC_API_KEY — jamais commité en vrai
├── Dockerfile                 # multi-stage: node build → python runtime
└── docker-compose.yml         # dev local
```

---

## 6. CI/CD GitHub Actions — explication et workflows

### Principe
Deux workflows séparés pour que la CI reste rapide et que le déploiement ne se déclenche que sur `main`.

### `ci.yml` — à chaque push et PR
1. `actions/checkout`
2. Backend : service `postgres:16` démarré par le job, `uv sync` (ou `pip install -e .[dev]`), `ruff check`, `pytest` sur cette base (LLM mocké, aucune clé API nécessaire).
3. Frontend : `npm ci`, `ng build --configuration production`, `ng test --watch=false` (si des specs existent).
4. Échoue → la PR est rouge. Rien n'est déployé.

### `deploy.yml` — sur push `main` uniquement
1. `docker/setup-buildx-action` + `docker/login-action` sur `ghcr.io` avec `GITHUB_TOKEN` (fourni automatiquement, aucun secret à créer pour pousser l'image).
2. `docker/build-push-action` : construit l'image multi-stage, tags `ghcr.io/<user>/sat-verbatim-analyzer:sha-<short>` et `:latest`. Utilise le cache GHA (`cache-from/to: type=gha`) pour ne pas rebuilder Angular à chaque fois.
3. Déploiement : `kubectl set image deployment/verbatim-analyzer app=ghcr.io/...:sha-<short> -n sat` puis `kubectl rollout status`.
   - Nécessite le secret `KUBECONFIG_B64` (kubeconfig encodé base64) dans *Settings → Secrets → Actions*.
   - **Prérequis** : l'API server K3s doit être joignable depuis les runners GitHub (VPS avec port 6443 ouvert et restreint, ou un ServiceAccount dédié au namespace `sat` avec un kubeconfig minimal — recommandé plutôt que l'admin).
   - Si le K3s est chez toi derrière NAT : **self-hosted runner** sur la machine (`actions/runner` installé en service) et le job tourne en local avec `runs-on: self-hosted`. Alternative `[V2]` : ArgoCD Image Updater qui tire l'image.
4. Le pull de l'image par K3s depuis GHCR : si le package est **public**, aucun secret ; sinon créer un `imagePullSecret` de type `docker-registry` avec un PAT `read:packages`.

### Secrets à créer sur le repo
- `KUBECONFIG_B64` (déploiement)
- rien d'autre : la clé Anthropic vit dans le cluster (`Secret` K8s), jamais dans GitHub.

---

## 7. Plan par session — avec définition de « fini »

### Session 1 (2-3h) — Données + pipeline en CLI
- [x] Init repo, `pyproject.toml`, `CLAUDE.md`, `.env.example`, `.gitignore`.
- [x] `scripts/generate_dataset.py` : appelle Claude pour produire 200 verbatims télécom/mobile money avec le bruit décrit en §0 (distribution visée : ~35 % négatif, 30 % positif, 20 % neutre, 15 % mixte/bruit). Résultat commité dans `data/samples/`.
- [x] `preprocess.py` + tests unitaires.
- [x] `llm_client.py` (wrapper SDK, usage logging, retries).
- [x] `extract.py`, `cluster.py`, `synthesize.py` + prompts.
- [x] `run_pipeline_cli.py data/samples/telecom_satisfaction_200.csv` → écrit `out/result.json` + affiche le récap tokens.
- **Fini quand** : le CLI tourne de bout en bout sur le CSV de démo, le JSON contient sentiment + thèmes par verbatim, 6-10 thèmes canoniques et une synthèse lisible, et le coût est affiché.

### Session 2 (2-3h) — API FastAPI + persistance + async
- [ ] `models.py`, `db.py`, `analysis_service.py` (met à jour `progress`/`current_step` à chaque lot).
- [ ] Routes §4. `POST` renvoie 202 et lance `BackgroundTasks`.
- [ ] Cache par `content_hash` (§2.6).
- [ ] `test_api.py` avec pipeline mocké.
- [ ] `docker-compose.yml` pour le dev.
- **Fini quand** : `curl -F file=@data/samples/... -F context=... localhost:8000/api/analyses` → 202, puis le `GET` passe de `processing` à `done` avec les résultats ; `pytest` vert.

### Session 3 (2-3h) — Dashboard Angular
- [ ] `ng new frontend --standalone --routing --style=scss`, proxy vers le backend en dev.
- [ ] `api.service.ts` typé sur les schémas §4, service de polling (`timer` + `switchMap` + `takeWhile`).
- [ ] Page **liste** : analyses + bouton « Nouvelle analyse ».
- [ ] Page **nouvelle analyse** : upload CSV, champ contexte, redirection vers le détail.
- [ ] Page **détail** : barre de progression + étape courante ; puis 4 blocs : KPIs (total, filtrés, répartition sentiments en donut), thèmes (cards ou barres horizontales triées, avec mini-répartition sentiments et verbatims représentatifs), table verbatims paginée + filtres sentiment/thème, synthèse exécutive (Markdown rendu) et panneau coût/tokens.
- [ ] Graphiques : `ng2-charts` (Chart.js). Pas de lib UI lourde ; Angular Material acceptable si ça fait gagner du temps sur la table et les chips.
- **Fini quand** : on peut uploader le CSV, regarder la progression, et lire tous les résultats sans ouvrir Swagger.

### Session 4 (2-3h) — Dockerisation, K3s, CI/CD, README
- [ ] `Dockerfile` multi-stage, FastAPI sert `static/` avec fallback SPA.
- [ ] Manifests `deploy/k8s/` (Deployment 1 réplica, resources requests/limits, readiness sur `/health`, Secret clé API, base PostgreSQL selon la décision prise avant la session 4, Ingress nginx avec host).
- [ ] `ci.yml` + `deploy.yml` (§6). Premier déploiement, vérification de bout en bout sur l'URL publique.
- [ ] README (§8), capture d'écran du dashboard, GIF ou vidéo courte de la démo.
- [ ] Tag `v1.0.0`.
- **Fini quand** : l'URL publique répond, une analyse complète tourne depuis le dashboard déployé, le README est lisible par un non-technicien en 3 minutes.

### Marge
S'il reste du temps en session 4, dans cet ordre : export CSV enrichi, ArgoCD Application manifest, SSE à la place du polling. **Pas avant que la checklist « fini » de la session 4 soit cochée.**

---

## 8. README — structure imposée

1. **Titre + une phrase** (« Analyse automatique de verbatims d'enquêtes de satisfaction avec Claude »)
2. **Démo** : URL publique, capture du dashboard, lien vidéo
3. **Besoin** : le problème de la SAT (volume de réponses ouvertes, codification manuelle lente et coûteuse, synthèse tardive)
4. **Solution** : schéma d'architecture, les 3 étapes du pipeline, pourquoi ce découpage (tokens, cohérence des thèmes), stack
5. **Résultat** : sur 200 verbatims — nb d'appels, tokens, coût estimé, durée, exemple de thèmes et extrait de synthèse. Chiffres **mesurés**, pas estimés.
6. **Lancer en local** : `docker compose up`, variables d'env, format du CSV
7. **Déploiement** : K3s + GitHub Actions, en 10 lignes
8. **Limites & V2** : honnête et court (Batches API, multi-langue, évaluation de la qualité du codage vs codeur humain)

---

## 9. Décisions prises (ne pas rouvrir en V1)

| Sujet | Décision | Pourquoi |
|---|---|---|
| Dashboard | Angular, standalone components | Stack du candidat, attendu par la SAT |
| Async | `BackgroundTasks` + polling | Zéro infra en plus, suffisant pour 1 utilisateur démo |
| Base | PostgreSQL 16 (local d'abord, hébergement prod à décider avant la session 4) ; tests sur Postgres, service `postgres:16` en CI | Instance déjà installée chez le candidat ; tests sur le même moteur que l'exécution |
| Modèles | Haiku 5.5 extraction, Sonnet 5.5 regroupement + synthèse | Coût/qualité ; configurable par env |
| Sortie LLM | Tool use avec schéma strict : forcé sur Haiku (extraction), `auto` + `strict` + vérification sur Sonnet 5.5 (regroupement, génération), qui rejette le forçage ; Markdown (synthèse). Pas de `temperature` (rejetée par les modèles 5.5), `effort` réglé par étape | JSON fiable sans parsing fragile, compatible avec l'API des modèles 5.5 |
| Déploiement | Un conteneur, image sur GHCR, `kubectl set image` depuis GitHub Actions | Démontrable, compréhensible, une seule surface de panne |
| Langue | Doc et UI en français, code et commentaires en anglais | Convention du repo |

---

## 10. Outillage Claude Code (à mettre en place en début de session 1)

Ces outils vivent **dans le repo**, versionnés, pour que chaque session Claude Code démarre avec le même contexte. Vérifier les commandes d'installation exactes dans la doc Anthropic et celle de chaque serveur au moment de les configurer — ne pas se fier à des commandes de mémoire.

### 10.1 Serveurs MCP (`.mcp.json` à la racine)

| Serveur | Usage dans ce projet | Priorité |
|---|---|---|
| **GitHub** (serveur officiel `github/github-mcp-server`) | Créer le repo, ouvrir/fermer des issues par sous-tâche, lire les logs des workflows Actions qui échouent sans quitter le terminal | Haute — surtout session 4 pour déboguer la CI |
| **Context7** (`upstash/context7`) | Documentation à jour de FastAPI, SQLModel, Angular, ng2-charts, SDK Anthropic. Évite que Claude Code code contre une version périmée d'Angular ou du SDK | Haute — dès session 1 |
| **Kubernetes** (ex. `containers/kubernetes-mcp-server` ou équivalent) | `kubectl get/describe/logs` depuis Claude Code pour déboguer le déploiement K3s | Moyenne — session 4 uniquement ; `kubectl` dans le shell suffit si l'installation prend plus de 10 min |

À **ne pas** ajouter : un serveur MCP Anthropic/Claude API (inutile, le SDK Python suffit), un serveur base de données (Postgres se lit avec `psql` en shell).

Le fichier `.mcp.json` est commité **sans token** : les tokens (GitHub PAT `repo` + `workflow` + `read:packages`) passent par variables d'environnement référencées dans la config, jamais en clair.

### 10.2 Hooks (`.claude/settings.json`)

- **PostToolUse sur Edit/Write de fichiers `.py`** → `ruff check --fix` + `ruff format` sur le fichier modifié. Claude Code ne commet jamais de Python non formaté.
- **PostToolUse sur Edit/Write de fichiers `.ts`** → `npx prettier --write` sur le fichier.
- **PreToolUse sur Bash** contenant `git push` → script qui refuse si `.env`, `*.kubeconfig` ou `out/` sont dans l'index (`git diff --cached --name-only`). Filet de sécurité contre une fuite de clé.

### 10.3 Commandes custom (`.claude/commands/`)

- `/session-start` : lit `CLAUDE.md` et `IMPLEMENTATION.md` §7, identifie la première case non cochée, propose un plan en 10 lignes et **attend validation**.
- `/session-end` : coche les cases terminées dans §7, ajoute une ligne au `## Journal` de `CLAUDE.md`, lance `pytest` et `npm run build`, propose le message de commit.
- `/cost-report` : lit la table `llm_calls` de la dernière analyse (via `psql`) et affiche appels/tokens/coût par étape, prêt à coller dans le README §5.

### 10.4 Sous-agents (`.claude/agents/`) — optionnel

- `reviewer` : agent en lecture seule, lancé avant chaque commit de fin de phase, qui vérifie la checklist « fini » et les interdits de `CLAUDE.md`. Utile parce qu'il n'a pas vu le code s'écrire et ne se note pas lui-même.

### 10.5 Ce que l'utilisateur fait à la main, une seule fois

1. Créer le dossier racine, y déposer `IMPLEMENTATION.md` et `CLAUDE.md`, `git init`.
2. Créer le repo GitHub vide (ou laisser le MCP GitHub le faire).
3. Générer un PAT GitHub et l'exporter dans le shell (`export GITHUB_TOKEN=...`), jamais dans un fichier du repo.
4. Avoir la clé Anthropic dans `backend/.env` (ignoré par git).
5. Décider avant la session 4 : K3s sur VPS joignable (secret `KUBECONFIG_B64`) ou self-hosted runner (voir §6).
