# Prompts du pipeline

Ces fichiers sont chargés tels quels par `llm_client.py` comme **system prompt** de chaque étape. Destination dans le repo : `backend/app/pipeline/prompts/`. Ce README décrit, pour chaque étape, le message utilisateur à construire côté Python et le schéma du tool à déclarer. Les prompts sont en français (c'est du contenu métier) ; le code qui les assemble est en anglais.

Toute modification d'un prompt doit incrémenter `PROMPT_VERSION` dans `config.py` : cette version entre dans le hash de cache des analyses (§2.6 d'`IMPLEMENTATION.md`).

---

## 1. `extract_system.md` — extraction par lot

**Modèle** : `EXTRACT_MODEL` (défaut `claude-haiku-5-5`). **Effort** : `low`. **Pas de `temperature`** (rejetée par les modèles 5.5). **max_tokens** : 1 500.

**System prompt** : contenu du fichier, dans un bloc avec `cache_control: {"type": "ephemeral"}`. Il est identique pour tous les lots et toutes les analyses ; c'est lui qui est mis en cache. Vérifier au premier appel que `cache_creation_input_tokens > 0`, puis `cache_read_input_tokens > 0` sur les suivants ; si le cache ne s'active pas, le prompt est sous le seuil minimal du modèle et il faut l'allonger (ajouter des exemples), pas le raccourcir.

**Message utilisateur** (gabarit, construit en Python) :
```
Contexte de l'enquête : {context}

Verbatims :
{idx}: {text_norm}
{idx}: {text_norm}
...
```
Un verbatim par ligne, 25 par lot. `idx` est l'index d'origine dans le CSV. Pas de JSON en entrée.

**Tool** (déclaré dans `tools` avec `strict: true`, imposé par `tool_choice: {"type": "tool", "name": "record_extraction"}`, accepté par Haiku 5.5). Le schéma ci-dessous est indicatif : la source unique est `schemas.py` ; les contraintes non supportées en mode strict (`minItems` > 1, `maxItems`) sont retirées du schéma envoyé et revalidées par Pydantic :
```json
{
  "name": "record_extraction",
  "description": "Record sentiment and themes for every verbatim in the batch.",
  "input_schema": {
    "type": "object",
    "properties": {
      "results": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "idx": {"type": "integer"},
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
            "themes": {
              "type": "array",
              "items": {"type": "string"},
              "minItems": 1,
              "maxItems": 3
            },
            "key_phrase": {"type": "string"}
          },
          "required": ["idx", "sentiment", "themes"]
        }
      }
    },
    "required": ["results"]
  }
}
```

**Validation côté Python** après l'appel :
- l'ensemble des `idx` renvoyés doit égaler l'ensemble des `idx` envoyés ; les manquants sont relancés une fois dans un mini-lot, puis marqués `extraction_failed` ;
- normaliser les libellés de thèmes : `strip()`, minuscules, espaces multiples réduits — le modèle est déjà briefé mais la normalisation locale garantit l'homogénéité entre lots ;
- `key_phrase` tronquée à 80 caractères si dépassement.

---

## 2. `cluster_system.md` — regroupement des thèmes

**Modèle** : `CLUSTER_MODEL` (défaut `claude-sonnet-5-5`). **Effort** : `low`. **Pas de `temperature`**. **max_tokens** : 4 000 (la réflexion adaptative compte dedans). **Un seul appel par analyse.**

**Message utilisateur** (gabarit) :
```
Contexte : {context}
Total : {total_occurrences} occurrences, {n_distinct} libellés distincts.

{label} ({count})
{label} ({count})
...
```
Libellés bruts **uniques**, triés par `count` décroissant. Jamais les verbatims.

**Tool** (`strict: true`, `tool_choice: auto` : Sonnet 5.5 rejette le forçage. On vérifie qu'un bloc `tool_use` `record_theme_mapping` est revenu, sinon un seul nouvel essai) :
```json
{
  "name": "record_theme_mapping",
  "description": "Record the final coding grid: canonical themes and the raw labels each one absorbs.",
  "input_schema": {
    "type": "object",
    "properties": {
      "themes": {
        "type": "array",
        "minItems": 6,
        "maxItems": 10,
        "items": {
          "type": "object",
          "properties": {
            "label": {"type": "string"},
            "description": {"type": "string"},
            "raw_labels": {"type": "array", "items": {"type": "string"}, "minItems": 1}
          },
          "required": ["label", "description", "raw_labels"]
        }
      }
    },
    "required": ["themes"]
  }
}
```

**Validation côté Python** :
- construire le dictionnaire `raw_label -> theme` ; tout libellé brut absent du mapping est rattaché à un thème « Autres remarques » (créé s'il n'existe pas), **sans second appel** ;
- un libellé présent dans deux thèmes est conservé dans le premier rencontré ;
- un `raw_label` renvoyé qui ne correspond à aucun libellé envoyé est ignoré avec un log `warning` (le modèle a reformulé malgré la consigne) ;
- recalculer localement `count` et `sentiment_breakdown` par thème à partir des verbatims, ne jamais faire confiance à un chiffre venant du modèle.

---

## 3. `synthesize_system.md` — synthèse exécutive

**Modèle** : `SYNTH_MODEL` (défaut `claude-sonnet-5-5`). **Effort** : `low`. **Pas de `temperature`**. **max_tokens** : 3 000 (réflexion incluse). Lire la réponse par type de bloc (`text`), la réponse peut commencer par un bloc `thinking`. **Pas de tool** : la réponse est le Markdown lui-même, stocké tel quel dans `Analysis.synthesis_md`. **Un seul appel par analyse.**

**Message utilisateur** (gabarit) :
```
Contexte : {context}

Totaux : {n_received} verbatims reçus, {n_used} exploités, {n_skipped} écartés (vides ou doublons).

Sentiments : positif {n_pos} ({pct_pos} %), neutre {n_neu} ({pct_neu} %), négatif {n_neg} ({pct_neg} %), mixte {n_mix} ({pct_mix} %).

Thèmes (par effectif décroissant) :

### {label} — {count} mentions ({pct} %)
{description}
Sentiments : positif {p} %, neutre {n} %, négatif {g} %, mixte {m} %
Extraits :
- « {excerpt_1} »
- « {excerpt_2} »
- « {excerpt_3} »

### ...
```
Extraits : 2 à 3 par thème, choisis localement (priorité aux verbatims qui portent une `key_phrase`, puis les plus courts), tronqués à 200 caractères avec « … » si coupés. Les thèmes « Appréciation générale » et « Autres remarques » sont inclus dans la liste (le modèle a besoin des chiffres) mais sans extraits.

**Validation côté Python** :
- vérifier que la réponse commence par `## Chiffres clés` et contient les quatre titres attendus ; sinon, un seul retry avec un message utilisateur complété par « Rappel : le document commence par `## Chiffres clés` et contient exactement quatre sections. » ;
- compter les mots : si > 500, log `warning`, on garde quand même (ne pas brûler un appel pour ça en V1).

---

## Budget de tokens attendu (200 verbatims, ~165 exploités après filtrage)

| Étape | Appels | System (cache) | Input par appel | Output par appel |
|---|---|---|---|---|
| extract | 7 | ~2 500 (lu depuis le cache dès le 2e appel) | ~900 | ~700 |
| cluster | 1 | ~1 200 | ~1 000 | ~600 |
| synthesize | 1 | ~800 | ~2 500 | ~700 |

Ces chiffres sont des ordres de grandeur à remplacer par les valeurs mesurées via `/cost-report`.
