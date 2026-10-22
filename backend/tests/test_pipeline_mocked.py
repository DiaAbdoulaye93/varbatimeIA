"""Pipeline steps with FakeLlmClient: no network, canned JSON fixtures."""

import re
from typing import Any

import pytest

from app.config import Settings
from app.pipeline import cluster as cluster_step
from app.pipeline import extract as extract_step
from app.pipeline import synthesize as synthesize_step
from app.pipeline.check import InputRejected, spread_sample
from app.pipeline.llm_client import LlmError
from app.pipeline.pipeline import run_pipeline
from app.pipeline.preprocess import preprocess
from app.schemas import AnalysisStats, ExtractionItem, ThemeMapping
from tests.fakes import SURVEY_OK, FakeLlmClient, load_fixture, load_text_fixture

CONTEXT = "Enquête de satisfaction, opérateur télécom, Dakar, septembre 2026."
SETTINGS = Settings()
LINE = re.compile(r"^(\d+): (.*)$", re.MULTILINE)

TEXTS = [
    "Le réseau coupe tout le temps à Pikine",  # 1
    "RAS",  # 2 -> empty
    "Le 1234 ne répond jamais",  # 3
    "dafa baax l'appli",  # 4
    "  le réseau coupe tout le temps à PIKINE ",  # 5 -> duplicate_of:1
    "Frais de retrait trop élevés mais réseau correct",  # 6
    "bof",  # 7
    "Agence de Thiès très accueillante",  # 8
]

# keyword -> (sentiment, raw themes, key phrase)
RULES: list[tuple[str, tuple[str, list[str], str | None]]] = [
    ("réseau coupe", ("negative", ["Couverture  Réseau."], "coupe tout le temps")),
    ("1234", ("negative", ["service client"], None)),
    ("appli", ("positive", ["application mobile"], None)),
    ("Frais", ("mixed", ["frais de retrait", "couverture réseau"], None)),
    ("bof", ("negative", ["appréciation générale"], None)),
    ("Agence", ("positive", ["accueil en agence"], None)),
]


def extraction_payload(user: str, drop: frozenset[int] = frozenset()) -> dict[str, Any]:
    results = []
    for idx, text in LINE.findall(user):
        if int(idx) in drop:
            continue
        sentiment, themes, key_phrase = next(v for k, v in RULES if k in text)
        results.append(
            {"idx": int(idx), "sentiment": sentiment, "themes": themes, "key_phrase": key_phrase}
        )
    return {"results": results}


def item(idx: int, sentiment: str, themes: list[str], key: str | None = None) -> ExtractionItem:
    return ExtractionItem.model_validate(
        {"idx": idx, "sentiment": sentiment, "themes": themes, "key_phrase": key}
    )


# --- extract ---


def test_clean_item_normalizes_labels_and_bounds() -> None:
    raw = item(1, "negative", ["  Service CLIENT.", "service client", "a", "b", "c"], "x" * 120)
    cleaned = extract_step.clean_item(raw)
    assert cleaned.themes == ["service client", "a", "b"]
    assert cleaned.key_phrase == "x" * extract_step.KEY_PHRASE_MAX_CHARS


def test_extract_batches_and_retries_missing_idx_once() -> None:
    verbatims = preprocess([f"Le réseau coupe, cas {i}" for i in range(30)])
    calls = 0

    def responder(user: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        # The two regular batches drop idx 7 and 29; the retry recovers 7 but not 29.
        drop = frozenset({7, 29}) if calls <= 2 else frozenset({29})
        payload = extraction_payload(user, drop=drop)
        payload["results"].append({"idx": 999, "sentiment": "neutral", "themes": ["x"]})
        return payload

    client = FakeLlmClient(tool_payloads={"record_extraction": [responder]})
    progress: list[tuple[int, int]] = []
    results = extract_step.extract(
        client, SETTINGS, verbatims, CONTEXT, on_progress=lambda d, t: progress.append((d, t))
    )
    assert progress == [(1, 2), (2, 2)]
    assert len(client.calls) == 3  # 25 + 5, then one mini-batch with idx 7 and 29
    assert "7: Le réseau coupe, cas 6" in client.calls[2]["user"]
    assert set(results) == set(range(1, 31)) - {29}  # 999 (unknown idx) is ignored
    assert client.calls[0]["user"].startswith(f"Contexte de l'enquête : {CONTEXT}\n\nVerbatims :")


def test_extract_survives_a_failed_batch() -> None:
    verbatims = preprocess(["Le réseau coupe ici", "Le réseau coupe là"])
    attempts = iter([LlmError("boom"), None])

    def responder(user: str) -> dict[str, Any]:
        error = next(attempts)
        if error:
            raise error
        return extraction_payload(user)

    client = FakeLlmClient(tool_payloads={"record_extraction": [responder]})
    assert set(extract_step.extract(client, SETTINGS, verbatims, CONTEXT)) == {1, 2}


# --- cluster ---


def cluster_inputs() -> tuple[dict[int, ExtractionItem], dict[int, str]]:
    extractions = {
        1: item(1, "negative", ["couverture réseau"], "coupe tout le temps"),
        3: item(3, "negative", ["service client"]),
        4: item(4, "positive", ["application mobile"]),
        6: item(6, "mixed", ["frais de retrait", "couverture réseau"]),
        7: item(7, "negative", ["appréciation générale"]),
        8: item(8, "positive", ["accueil en agence"]),
        9: item(9, "negative", ["couverture réseau"]),
    }
    texts = {idx: f"texte {idx}" for idx in extractions}
    texts[9] = "court"
    return extractions, texts


def test_cluster_user_message_lists_labels_by_frequency() -> None:
    extractions, _ = cluster_inputs()
    message = cluster_step.build_user_message(CONTEXT, cluster_step.count_labels(extractions))
    assert "Total : 8 occurrences, 6 libellés distincts." in message
    assert message.split("\n\n")[1].splitlines()[0] == "couverture réseau (3)"


def test_cluster_maps_locally_and_never_trusts_model_counts() -> None:
    extractions, texts = cluster_inputs()
    client = FakeLlmClient(
        tool_payloads={"record_theme_mapping": [load_fixture("cluster_mapping.json")]}
    )
    themes, theme_ids = cluster_step.cluster(client, SETTINGS, extractions, texts, CONTEXT)

    by_label = {t.label: t for t in themes}
    # "couverture réseau" is claimed twice: the first theme wins.
    assert by_label["Couverture réseau"].raw_labels == ["couverture réseau"]
    assert by_label["Application mobile"].raw_labels == ["application mobile"]
    # Unknown label "attente au 1234" ignored; case-insensitive match on "Service Client".
    assert by_label["Service client"].raw_labels == ["service client"]
    # "accueil en agence" was not mapped by the model.
    assert themes[-1].label == cluster_step.OTHER_LABEL
    assert themes[-1].raw_labels == ["accueil en agence"]

    reseau = by_label["Couverture réseau"]
    assert (reseau.id, reseau.count) == (1, 3)
    assert reseau.sentiment_breakdown == {"positive": 0, "neutral": 0, "negative": 2, "mixed": 1}
    # Key phrase first, then shortest text.
    assert reseau.representative_idx == [1, 9, 6]
    assert theme_ids[6] == [1, by_label["Tarification mobile money"].id]


def test_resolve_mapping_merges_a_model_provided_other_theme() -> None:
    counts = cluster_step.count_labels({1: item(1, "neutral", ["x", "y"])})
    mapping = ThemeMapping.model_validate(
        {"themes": [{"label": "Autres remarques", "description": "d", "raw_labels": ["x"]}]}
    )
    themes = cluster_step.resolve_mapping(mapping, counts)
    assert [(t.label, t.raw_labels) for t in themes] == [("Autres remarques", ["x", "y"])]


# --- synthesize ---


def synth_inputs() -> tuple[AnalysisStats, list[Any], dict[int, str]]:
    extractions, texts = cluster_inputs()
    texts[1] = "x" * 300
    client = FakeLlmClient(
        tool_payloads={"record_theme_mapping": [load_fixture("cluster_mapping.json")]}
    )
    themes, _ = cluster_step.cluster(client, SETTINGS, extractions, texts, CONTEXT)
    stats = AnalysisStats(
        n_received=9,
        n_used=7,
        n_skipped=2,
        n_failed=0,
        sentiment_counts={"positive": 2, "neutral": 0, "negative": 4, "mixed": 1},
    )
    return stats, themes, texts


def test_synthesis_message_has_figures_and_truncated_excerpts() -> None:
    stats, themes, texts = synth_inputs()
    message = synthesize_step.build_user_message(CONTEXT, stats, themes, texts)
    assert "Totaux : 9 verbatims reçus, 7 exploités, 2 écartés" in message
    assert "positif 2 (29 %), neutre 0 (0 %), négatif 4 (57 %), mixte 1 (14 %)" in message
    assert "### Couverture réseau — 3 mentions (43 %)" in message
    assert f"« {'x' * 199}… »" in message
    general = message.split("### Appréciation générale")[1].split("###")[0]
    assert "Extraits" not in general


def test_synthesis_retries_once_with_a_reminder() -> None:
    stats, themes, texts = synth_inputs()
    client = FakeLlmClient(texts=["Voici la synthèse :", load_text_fixture("synthesis.md")])
    markdown = synthesize_step.synthesize(client, SETTINGS, stats, themes, texts, CONTEXT)
    assert markdown.startswith("## Chiffres clés")
    assert len(client.calls) == 2
    assert client.calls[1]["user"].endswith(synthesize_step.REMINDER)


# --- end to end ---


def test_run_pipeline_end_to_end() -> None:
    client = FakeLlmClient(
        tool_payloads={
            "record_file_check": [SURVEY_OK],
            "record_extraction": [extraction_payload],
            "record_theme_mapping": [load_fixture("cluster_mapping.json")],
        },
        texts=[load_text_fixture("synthesis.md")],
    )
    steps: list[tuple[str, int]] = []
    infos: list[Any] = []

    def on_progress(step: str, progress: int, info: Any) -> None:
        steps.append((step, progress))
        infos.append(info)

    result = run_pipeline(client, SETTINGS, TEXTS, CONTEXT, on_progress=on_progress)
    assert infos[-1].model_dump() == {
        "n_kept": 6,
        "n_skipped": 2,
        "batch_done": 1,
        "batch_total": 1,
    }

    assert result.stats.model_dump() == {
        "n_received": 8,
        "n_used": 6,
        "n_skipped": 2,
        "n_failed": 0,
        "n_flagged": 0,
        "sentiment_counts": {"positive": 2, "neutral": 0, "negative": 3, "mixed": 1},
    }
    duplicate = result.verbatims[4]
    assert duplicate.skipped_reason == "duplicate_of:1"
    assert duplicate.sentiment == "negative" and duplicate.theme_ids == [1]
    assert result.verbatims[1].sentiment is None
    assert result.synthesis_md.startswith("## Chiffres clés")
    assert [u.step for u in result.usage] == ["check", "extract", "cluster", "synthesize"]
    assert [s for s, _ in steps][-1] == "done"
    assert [p for _, p in steps] == sorted(p for _, p in steps)


def test_extraction_items_reject_unknown_sentiment() -> None:
    with pytest.raises(ValueError):
        item(1, "angry", ["x"])


# --- AI control ---


def flagging_payload(user: str) -> dict[str, Any]:
    """Like extraction_payload, but flags the 1234 answer and the agency answer."""
    payload = extraction_payload(user)
    for item in payload["results"]:
        if item["idx"] == 3:
            item["flag"] = "manipulation"
        elif item["idx"] == 8:
            item["flag"] = "off_topic"
    return payload


def test_flagged_verbatims_are_excluded_from_themes_and_stats() -> None:
    client = FakeLlmClient(
        tool_payloads={
            "record_file_check": [SURVEY_OK],
            "record_extraction": [flagging_payload],
            "record_theme_mapping": [load_fixture("cluster_mapping.json")],
        },
        texts=[load_text_fixture("synthesis.md")],
    )
    result = run_pipeline(client, SETTINGS, TEXTS, CONTEXT)

    assert (result.stats.n_used, result.stats.n_flagged, result.stats.n_failed) == (4, 2, 0)
    by_idx = {v.idx: v for v in result.verbatims}
    assert by_idx[3].skipped_reason == "manipulation" and by_idx[3].sentiment is None
    assert by_idx[8].skipped_reason == "off_topic" and by_idx[8].theme_ids == []
    cluster_message = next(c["user"] for c in client.calls if c["step"] == "cluster")
    assert "service client" not in cluster_message
    assert "accueil en agence" not in cluster_message


def test_file_check_rejects_a_non_survey_file_before_extraction() -> None:
    rejected = {"is_survey": False, "reason": "Ce document semble être un contrat."}
    client = FakeLlmClient(tool_payloads={"record_file_check": [rejected]})
    with pytest.raises(InputRejected, match="contrat"):
        run_pipeline(client, SETTINGS, TEXTS, CONTEXT)
    assert [c["step"] for c in client.calls] == ["check"]


def test_file_check_sample_spreads_over_the_whole_file() -> None:
    verbatims = preprocess([f"réponse numéro {i}" for i in range(100)])
    sample = spread_sample(verbatims, 10)
    assert len(sample) == 10
    assert sample[0].idx == 1 and sample[-1].idx > 85
