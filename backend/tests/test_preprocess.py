"""Local preprocessing: unit cases and the demo CSV checked against its gold labels."""

import csv
from pathlib import Path

import pytest

from app.pipeline.preprocess import MAX_CHARS, normalize, preprocess

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"
INPUT_CSV = SAMPLES_DIR / "telecom_satisfaction_200.csv"
GOLD_CSV = SAMPLES_DIR / "telecom_satisfaction_200.gold.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_normalize_collapses_all_whitespace_and_keeps_case() -> None:
    assert normalize("\t  Le Réseau \n\n coupe  ") == "Le Réseau coupe"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "RAS",
        "ras",
        "R.A.S",
        "r.a.s.",
        "Rien",
        "rien à signaler",
        "Aucun",
        ".",
        "-",
        "ok",
    ],
)
def test_non_informative_answers_are_skipped(text: str) -> None:
    assert preprocess([text])[0].skipped_reason == "empty"


@pytest.mark.parametrize("text", ["nul", "bof", "Rien à dire, tout va bien", "RAS sur le réseau"])
def test_short_but_meaningful_answers_are_kept(text: str) -> None:
    assert preprocess([text])[0].skipped_reason is None


def test_duplicates_point_to_the_first_occurrence() -> None:
    results = preprocess(["Réseau nul", "autre chose", "  réseau   NUL\n", "Réseau nul"])
    assert [r.skipped_reason for r in results] == [
        None,
        None,
        "duplicate_of:1",
        "duplicate_of:1",
    ]
    assert [r.idx for r in results] == [1, 2, 3, 4]


def test_empty_answers_are_not_used_as_duplicate_originals() -> None:
    results = preprocess(["RAS", "ras", "bon réseau"])
    assert [r.skipped_reason for r in results] == ["empty", "empty", None]


def test_long_verbatims_are_truncated_but_raw_text_is_kept() -> None:
    text = "a" * (MAX_CHARS + 50)
    result = preprocess([text])[0]
    assert result.truncated and len(result.text_norm) == MAX_CHARS
    assert result.text == text and result.skipped_reason is None


def test_demo_csv_noise_matches_gold_labels() -> None:
    inputs = read_csv(INPUT_CSV)
    gold = {row["id"]: row for row in read_csv(GOLD_CSV)}
    results = preprocess([row["verbatim"] for row in inputs])

    first_idx_by_norm: dict[str, int] = {}
    for row, result in zip(inputs, results, strict=True):
        assert result.idx == int(row["id"])
        noise = gold[row["id"]]["noise"]
        key = normalize(row["verbatim"]).lower()
        if noise in ("empty", "ras"):
            assert result.skipped_reason == "empty", row
        elif noise.startswith("duplicate_of:"):
            assert result.skipped_reason == noise, row
        elif noise == "whitespace":
            assert result.skipped_reason == f"duplicate_of:{first_idx_by_norm[key]}", row
        else:
            assert result.skipped_reason is None, row
            first_idx_by_norm.setdefault(key, result.idx)

    skipped = sum(1 for r in results if r.skipped_reason)
    assert skipped == 20
