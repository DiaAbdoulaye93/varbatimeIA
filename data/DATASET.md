# Jeu de données de démo — spécification de `scripts/generate_dataset.py`

Objectif : disposer dès la première demi-heure de la session 1 d'un CSV de ~200 verbatims réalistes, **commité dans le repo** (`data/samples/`), avec des étiquettes de référence séparées pour mesurer la qualité du pipeline. Le script est exécuté une fois ; le CSV produit devient la donnée de démo officielle. On ne le régénère pas à chaque session (tokens + reproductibilité).

## Sorties

| Fichier | Rôle | Commité |
|---|---|---|
| `data/samples/telecom_satisfaction_200.csv` | **Entrée du pipeline.** Colonnes : `id`, `verbatim`. C'est ce qu'on uploade dans le dashboard. | Oui |
| `data/samples/telecom_satisfaction_200.gold.csv` | **Étiquettes de référence.** Colonnes : `id`, `expected_sentiment`, `expected_topics` (séparés par `;`), `noise` (vide, ou `empty`, `ras`, `duplicate_of:<id>`, `whitespace`). Jamais envoyé au pipeline. | Oui |
| `data/samples/generation_log.json` | Tokens et modèle utilisés pour la génération, à des fins de transparence dans le README. | Oui |

Format CSV : UTF-8, séparateur virgule, texte entre guillemets doubles, `id` entier croissant à partir de 1. Pas de BOM.

## Déroulement du script

1. **Génération par Claude** — 4 appels de 45 verbatims chacun (180 verbatims « propres »).
   - System prompt : `backend/app/pipeline/prompts/dataset_system.md` (avec `cache_control`, il est identique sur les 4 appels).
   - Message utilisateur : `Lot {n} sur 4. Produis 45 verbatims.` Varier le numéro de lot suffit à obtenir des contenus différents ; ajouter sur les lots 2 à 4 la ligne `Ne réutilise aucune formulation d'un lot précédent.` est inutile puisque le modèle ne les voit pas, donc ne pas l'écrire.
   - Modèle : `claude-sonnet-5-5`, `temperature: 1.0` (diversité), `max_tokens: 6000`.
   - Tool forcé `record_verbatims` :
     ```json
     {
       "name": "record_verbatims",
       "description": "Record the generated survey verbatims with their reference labels.",
       "input_schema": {
         "type": "object",
         "properties": {
           "verbatims": {
             "type": "array",
             "items": {
               "type": "object",
               "properties": {
                 "text": {"type": "string"},
                 "expected_sentiment": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
                 "expected_topics": {
                   "type": "array", "minItems": 1, "maxItems": 2,
                   "items": {"type": "string", "enum": ["reseau", "service_client", "tarif_mobile_money", "tarif_forfait", "application", "agence", "delai", "general"]}
                 }
               },
               "required": ["text", "expected_sentiment", "expected_topics"]
             }
           }
         },
         "required": ["verbatims"]
       }
     }
     ```
   - Après chaque appel : dédoublonner sur le texte normalisé (le modèle peut se répéter à l'intérieur d'un lot), tronquer à 600 caractères, logger le nombre obtenu. Si le total final est < 170, relancer un appel de complément ; sinon accepter.

2. **Injection de bruit en local** (0 token, `random.seed(42)` pour la reproductibilité) — ajouter ~20 lignes :
   - 5 vides (`""`), `noise = empty`
   - 5 non informatifs tirés de `["RAS", "ras", "R.A.S", "rien", "Rien à signaler", "-", ".", "aucun"]`, `noise = ras`
   - 6 doublons exacts de verbatims existants (choisis au hasard parmi les 180), `noise = duplicate_of:<id>`
   - 4 variantes « espaces » : un verbatim existant entouré d'espaces, tabulations ou sauts de ligne, `noise = whitespace` — ils doivent être dédoublonnés par le prétraitement après normalisation, c'est ce qu'on teste.

3. **Mélange** de l'ensemble (même seed), attribution des `id`, écriture des deux CSV et du log.

4. **Contrôle affiché en fin de script** : effectifs par sentiment attendu, par sujet, par type de bruit, longueur moyenne/min/max, part de verbatims contenant au moins un mot wolof de la liste du prompt. Si la distribution de sentiments s'écarte de plus de 8 points de la cible (35/30/20/15), le dire en `warning` — on accepte quand même en V1.

## Utilisation des étiquettes de référence (session 1, optionnel mais bon marché)

`run_pipeline_cli.py --gold data/samples/telecom_satisfaction_200.gold.csv` ajoute au récap :
- **Exactitude du sentiment** : part des verbatims non bruités où `sentiment == expected_sentiment`. Indiquer aussi l'exactitude en regroupant `mixed` avec la polarité la plus proche, car c'est la catégorie la plus discutable.
- **Couverture des sujets** : pour chaque `expected_topic`, part des verbatims dont au moins un thème canonique a été associé manuellement à ce sujet. L'association sujet ↔ thème canonique est un petit dictionnaire écrit à la main après le premier run, dans `data/samples/topic_mapping.json` ; pas d'appel LLM.
- **Bruit** : vérifier que les 20 lignes `noise` ont bien `skipped_reason` renseigné et que les doublons/variantes espaces pointent vers le bon original.

Ces trois chiffres vont dans le README §5 « Résultat ». C'est ce qui différencie une démo d'un jouet : on ne dit pas « ça marche », on dit « 91 % d'accord avec l'étiquette de référence sur le sentiment, 100 % des doublons détectés ».

## Ce que le script ne fait pas

- Pas de génération à la volée depuis l'API ou le dashboard. Le dataset est un fichier statique du repo.
- Pas de régénération automatique : lancer `generate_dataset.py` écrase les CSV, donc le script refuse de s'exécuter si les fichiers existent, sauf avec `--force`.
- Pas d'étiquettes de référence dans le CSV d'entrée : le pipeline ne doit jamais les voir.
