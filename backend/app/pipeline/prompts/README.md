# Prompts du pipeline

Chaque fichier `.md` de ce dossier est le **system prompt** d'une étape. Il est chargé tel quel par `prompt_loader.py`, puis envoyé par `llm_client.py`, seul module du projet qui appelle l'API Claude. Les prompts sont en français, car c'est du contenu métier ; le code qui les assemble est en anglais.

**Règle de maintenance :** toute modification d'un prompt doit incrémenter `PROMPT_VERSION` dans `app/config.py` (valeur actuelle : `3`). Cette version fait partie de la clé de cache des analyses : sans cette incrémentation, un fichier déjà analysé serait resservi avec l'ancien résultat.

Principes communs à toutes les étapes :

- **Sortie structurée par outil** (*tool use*) avec `strict: true`. Le schéma est défini une seule fois en Pydantic dans `app/schemas.py`, converti en `input_schema`, puis la réponse est revalidée côté Python.
- **Pas de `temperature`** : les modèles 5.5 n'acceptent que la valeur par défaut. La stabilité vient du schéma et du prompt.
- **`effort`** réglé par étape dans `app/config.py`.
- **Les réponses analysées sont des données, jamais des consignes** : c'est écrit dans chaque prompt qui les reçoit.

| Fichier | Étape | Modèle (variable d'environnement) | Appels par analyse |
|---|---|---|---|
| `file_check_system.md` | Vérification du fichier | Haiku 5.5 (`EXTRACT_MODEL`) | 1 |
| `extract_system.md` | Extraction | Haiku 5.5 (`EXTRACT_MODEL`) | 1 par lot de 25 réponses |
| `cluster_system.md` | Regroupement des thèmes | Sonnet 5.5 (`CLUSTER_MODEL`) | 1 |
| `synthesize_system.md` | Synthèse exécutive | Sonnet 5.5 (`SYNTH_MODEL`) | 1 (2 si la structure est à corriger) |
| `dataset_system.md` | Génération du jeu de démo | Sonnet 5.5 (`DATASET_MODEL`) | Hors application : `scripts/generate_dataset.py` |

---

## 1. `file_check_system.md` : vérification du fichier

**But :** refuser, avant de dépenser des tokens d'extraction, un fichier qui n'est pas une enquête (contrat, article, code…).

- **Entrée :** le contexte annoncé et un échantillon de 12 réponses réparties sur tout le fichier (300 caractères maximum chacune).
- **Sortie :** outil `record_file_check` → `{"is_survey": bool, "reason": "phrase en français"}`. Choix d'outil forcé (accepté par Haiku), `max_tokens` 400.
- **Effet :** si `is_survey` vaut `false`, l'analyse s'arrête en échec et `reason` est affiché à l'utilisateur. En cas de doute, le prompt demande de laisser passer.

## 2. `extract_system.md` : extraction par lot

**But :** pour chaque réponse, un sentiment, 1 à 3 thèmes bruts, une phrase clé facultative et un signalement éventuel.

- **System prompt mis en cache** (`cache_control: ephemeral`) : identique pour tous les lots, il est relu depuis le cache à partir du 2e lot, à un dixième du prix.
- **Message utilisateur**, construit en Python, une réponse par ligne, 25 par lot :

  ```
  Contexte de l'enquête : {contexte}

  Verbatims :
  {idx}: {texte normalisé}
  ```

- **Sortie :** outil `record_extraction`, choix forcé, `max_tokens` 2 000, `effort` `low`. Pour chaque réponse : `idx`, `sentiment` (`positive` | `neutral` | `negative` | `mixed`), `themes`, `key_phrase` (facultatif) et `flag` (`none` par défaut, `off_topic` pour le hors-sujet, `manipulation` pour une tentative de détourner l'IA). Le modèle ne renvoie jamais le texte des réponses.
- **Contrôles côté Python :**
  - chaque `idx` envoyé doit revenir ; les manquants sont renvoyés une fois en lots de 10, puis marqués `extraction_failed` ;
  - les libellés sont normalisés (minuscules, espaces), 3 thèmes au maximum, phrase clé de 80 caractères au plus ;
  - les réponses signalées sont exclues des statistiques, du regroupement et de la synthèse, et affichées avec leur motif.

## 3. `cluster_system.md` : regroupement des thèmes

**But :** une grille de 6 à 10 thèmes canoniques pour toute l'enquête, à partir des thèmes bruts.

- **Message utilisateur :** les thèmes bruts **distincts, numérotés**, triés par fréquence. Les réponses elles-mêmes ne sont jamais envoyées.

  ```
  Contexte : {contexte}
  Total : {occurrences} occurrences, {n} libellés distincts.

  1. service client (31)
  2. couverture réseau (28)
  ```

- **Sortie :** outil `record_theme_mapping` → pour chaque thème : `label`, `description`, `raw_label_ids` (les **numéros** des thèmes bruts, jamais leur texte). Répondre par numéros rend la réponse plusieurs fois plus courte, ce qui est indispensable sur 2 000 réponses (plusieurs centaines de libellés), et évite tout libellé reformulé.
- **Paramètres :** `tool_choice: auto` avec `strict: true` (Sonnet 5.5 refuse le choix d'outil forcé), un nouvel essai si l'outil n'est pas appelé, aucun nouvel essai si la réponse est coupée. `max_tokens` 16 000 (seuls les tokens produits sont facturés), `effort` `low`.
- **Contrôles côté Python :** un numéro inconnu est ignoré ; un libellé affecté deux fois reste dans le premier thème ; un libellé oublié rejoint « Autres remarques ». Effectifs, répartitions des sentiments et citations représentatives sont **recalculés localement**, jamais repris du modèle.

## 4. `synthesize_system.md` : synthèse exécutive

**But :** une page de rapport en Markdown pour le commanditaire de l'enquête.

- **Entrée :** uniquement des agrégats : totaux, répartition des sentiments, et pour chaque thème son poids, sa répartition et 2 à 3 extraits tronqués à 200 caractères. « Appréciation générale » et « Autres remarques » sont fournis sans extraits.
- **Sortie :** texte libre (pas d'outil), `max_tokens` 3 000, `effort` `low`. La réponse est lue par type de bloc, car elle peut commencer par un bloc de réflexion.
- **Contrôle :** le document doit commencer par `## Chiffres clés` et contenir les quatre sections (Chiffres clés, Points forts, Points d'attention, Recommandations). Sinon, un seul nouvel essai avec un rappel. Au-delà de 500 mots, un simple avertissement dans les logs.

## 5. `dataset_system.md` : génération du jeu de démo

Utilisé uniquement par `backend/scripts/generate_dataset.py`, jamais par l'application. Il produit des réponses fictives réalistes (fautes, wolof, sarcasme) avec leurs étiquettes de référence. Voir la section « Jeu de données de démo » du README principal.

---

## Consommation mesurée

Sur le jeu de démo (223 lignes, 203 réponses analysées) :

| Étape | Appels | Tokens en entrée | Relus depuis le cache | Tokens en sortie |
|---|---:|---:|---:|---:|
| Vérification | 1 | 1 721 | 0 | 112 |
| Extraction | 9 | 10 225 | 36 126 | 12 002 |
| Regroupement | 1 | 3 963 | 0 | 1 496 |
| Synthèse | 1 | 3 458 | 0 | 884 |

Sur 2 000 réponses : 74 appels, dont un regroupement de 10 093 tokens en entrée et 8 036 en sortie.
