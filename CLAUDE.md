# CLAUDE.md — Conventions du repo `sat-verbatim-analyzer`

Ce fichier est lu par Claude Code au démarrage de chaque session. Il complète `IMPLEMENTATION.md`, qui reste la source de vérité pour le périmètre et le plan.

## Contexte en 3 lignes
Démonstrateur d'analyse de verbatims d'enquêtes (sentiment, thèmes, synthèse) via l'API Claude, pour une candidature chez la SAT. Backend FastAPI, dashboard Angular, déploiement K3s, CI/CD GitHub Actions. **Deadline V1 : 23/10/2026 matin.** Tout ce qui est `[V2]` dans `IMPLEMENTATION.md` est interdit en V1.

## Langues
- Réponses à l'utilisateur, README, docs, textes UI : **français**.
- Code, commentaires, noms de variables, messages de commit, docstrings : **anglais**.

## Outillage disponible
- Serveurs MCP configurés dans `.mcp.json` : **Context7** (toujours le consulter avant d'utiliser une API de FastAPI, SQLModel, Angular, ng2-charts ou du SDK Anthropic dont la version n'est pas certaine), **GitHub** (issues, lecture des runs Actions), **Kubernetes** (session 4 seulement).
- Commandes : `/session-start` pour ouvrir une session, `/session-end` pour la clore, `/cost-report` pour les chiffres du README.
- Les hooks formatent automatiquement `.py` et `.ts` et bloquent tout `git push` contenant un secret. Ne pas les contourner.

## Workflow attendu
- Toujours commencer une session par `/session-start`, la terminer par `/session-end`.
- Travailler **phase par phase** selon §7 d'`IMPLEMENTATION.md`. Ne pas commencer la phase N+1 tant que la checklist « fini » de la phase N n'est pas cochée.
- Avant d'écrire du code dans une phase : lire les fichiers concernés, proposer le plan en 5-10 lignes, attendre validation, puis implémenter.
- Un commit par sous-tâche cochée, message au format `feat(pipeline): add batch extraction with tool use`, `test(api): ...`, `chore(ci): ...`.
- À la fin de chaque session : mettre à jour les cases cochées dans `IMPLEMENTATION.md` §7 et noter dans `## Journal` ci-dessous ce qui a été fait et ce qui bloque.
- Ne jamais rouvrir une décision du §9 d'`IMPLEMENTATION.md`. Si une décision pose un vrai problème, le dire et attendre.

## Backend (Python 3.12, FastAPI)
- Gestion des dépendances : `uv` (`uv sync`, `uv run pytest`). Fallback `pip` si `uv` indisponible.
- Lint/format : `ruff` (config dans `pyproject.toml`). Lancer `uv run ruff check --fix . && uv run ruff format .` avant chaque commit.
- Typage strict : annotations partout, `pydantic` v2 pour les I/O, `SQLModel` pour les tables.
- Base : PostgreSQL 16 local (`localhost:5432`), URL lue depuis `DATABASE_URL` (`postgresql+psycopg://...`), jamais hardcodée. Tests sur la base `sat_verbatim_test`, recréée par les fixtures.
- Tests : `pytest`, **jamais d'appel réseau réel** en test. Le client LLM est injecté et mocké (`FakeLlmClient` renvoyant des fixtures JSON).
- Appels Claude : uniquement via `app/pipeline/llm_client.py`. Pas d'import direct de `anthropic` ailleurs. Chaque appel enregistre son usage (tokens, modèle, durée, étape).
- Sorties structurées : tool use avec `strict: true` ; `tool_choice` forcé sur Haiku 5.5, `auto` + vérification de l'appel sur Sonnet 5.5 (qui rejette le forçage). Schémas définis une seule fois en Pydantic dans `schemas.py`, convertis en `input_schema` et revalidés côté client. Jamais de `temperature` (rejetée par les modèles 5.5) ; `effort` par étape dans `config.py`.
- Prompts : fichiers `.md` dans `app/pipeline/prompts/`, chargés au démarrage, jamais de prompt en f-string inline. Le system prompt d'extraction porte `cache_control`.
- Noms de modèles : lus depuis `config.py` / variables d'env (`EXTRACT_MODEL`, `CLUSTER_MODEL`, `SYNTH_MODEL`). Ne pas hardcoder.
- Grille de prix dans `config.py` : vérifier les tarifs sur la doc Anthropic au moment de l'écrire, ne pas inventer.
- Pas de `print` : `logging` avec un logger par module.
- Secrets : `.env` ignoré par git, `.env.example` à jour.

## Frontend (Angular, dernière LTS)
- Standalone components, `inject()`, signals pour l'état local, `HttpClient` typé sur `core/models.ts` (miroir des schémas Pydantic).
- Pas de NgModule. Pas de state management externe (NgRx interdit en V1).
- Polling : `timer(0, 3000).pipe(switchMap(...), takeWhile(status not final, true))`.
- Graphiques : `ng2-charts`. UI : Angular Material autorisé pour table/chips/progress, sinon SCSS maison. Pas de Tailwind.
- `npm run lint` et `npm run build` doivent passer avant commit.
- Dev : proxy `proxy.conf.json` vers `http://localhost:8000`.

## Docker / K8s / CI
- Un seul `Dockerfile` multi-stage à la racine. L'image finale est `python:3.12-slim` + `dist/` Angular copié dans `backend/static/`.
- Manifests dans `deploy/k8s/`, namespace `sat`. Hébergement de Postgres en prod : à décider avant la session 4, ne rien supposer d'ici là. Secret `anthropic-api-key` créé à la main, jamais commité (`secret.example.yaml` seulement).
- Workflows : `.github/workflows/ci.yml` (tests) et `deploy.yml` (push `main` → GHCR → `kubectl set image`). Expliquer chaque step en commentaire YAML : l'auteur veut comprendre la CI.

## Interdits
- Démarrer une fonctionnalité `[V2]`.
- Ajouter Redis, Celery, NgRx, Tailwind, un second conteneur applicatif.
- Appeler l'API Claude dans les tests ou sans passer par `llm_client.py`.
- Renvoyer le texte des verbatims dans les sorties LLM (gaspillage de tokens).
- Commiter `.env`, un kubeconfig, une clé API, ou le dossier `out/`.

## Commandes utiles
```bash
# backend
cd backend && uv sync && uv run uvicorn app.main:app --reload
uv run pytest -q
uv run python scripts/run_pipeline_cli.py ../data/samples/telecom_satisfaction_200.csv

# frontend
cd frontend && npm ci && npm start

# backend dans Docker (dev, PostgreSQL de l'hôte)
POSTGRES_PASSWORD=... docker compose up
```

## Journal
<!-- Une ligne par session : date — fait / bloque -->
- 2026-10-21 — Plan rédigé (IMPLEMENTATION.md, CLAUDE.md). Rien d'implémenté.
- 2026-10-21 — Outillage Claude Code, passage à PostgreSQL, adaptation aux contraintes des modèles 5.5 (pas de `temperature`, pas de `tool_choice` forcé sur Sonnet). Session 1 terminée : dataset (223 lignes, 0,16 $), pipeline complet en CLI (11 appels, 0,047 $, 78 s, 95 % d'accord sentiment avec le gold, 20/20 bruits écartés). Session 2 : API, persistance, cache, tests (61 verts), vérifiée au `curl`. Bloquant : `docker-compose.yml` écrit et validé (`docker compose config`) mais pas lancé, Docker Desktop arrêté ; `topic_mapping.json` à écrire à la main pour la couverture des sujets.
- 2026-10-22 — Session 3 (dashboard Angular 21) et 3b : fichiers CSV/TSV/TXT/JSON/XLSX/DOCX/PDF, colonne de réponses détectée, refus des fichiers dangereux, contrôle IA (manipulation, hors-sujet, vérification du fichier). Vérifié en réel : 5 formats OK, contrat refusé, injection et spam signalés, aucun faux positif sur la démo (95 % sentiment, 12 appels, 0,046 $). Bloquant : build Docker jamais abouti (réseau instable), session 4 non commitée (Dockerfile, k8s, CI, README) en attente du test local de l'auteur ; décisions de déploiement à prendre (PostgreSQL prod, K3s, domaine).
- 2026-10-22 — Correctifs : regroupement des thèmes sur 2 000 réponses (numéros de libellés, max_tokens 16 000), lecture des listes numérotées, fichier source conservé et page « Réponses lues » imprimable. Déploiement Render + Neon (branche `prod`, mot de passe APP_PASSWORD). Prise en charge du PDF retirée à la demande de l'auteur : un PDF est refusé.
