"""Generate the demo dataset in data/samples/ with Claude. Run once (README, section 9).

Usage (from backend/): uv run python scripts/generate_dataset.py [--force] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import PRICING, Settings, get_settings
from app.pipeline.llm_client import AnthropicLlmClient, LlmClient
from app.pipeline.prompt_loader import load_prompt
from app.schemas import RECORD_VERBATIMS, GeneratedVerbatim

logger = logging.getLogger("generate_dataset")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "samples"
INPUT_FILE = "telecom_satisfaction_200.csv"
GOLD_FILE = "telecom_satisfaction_200.gold.csv"
LOG_FILE = "generation_log.json"

STEP = "dataset"
BATCH_COUNT = 4
BATCH_SIZE = 45
MIN_CLEAN_TOTAL = 170
MAX_CHARS = 600
MAX_TOKENS = 16_000
SEED = 42
USER_TEMPLATE = "Lot {batch} sur {total}. Produis {count} verbatims."

RAS_VARIANTS = ["RAS", "ras", "R.A.S", "rien", "Rien à signaler", "-", ".", "aucun"]
WHITESPACE_WRAPPERS = [("   ", "  "), ("\t", "\n"), ("\n  ", " \t"), ("", "   \n\n")]
EMPTY_COUNT = 5
RAS_COUNT = 5
DUPLICATE_COUNT = 6
WHITESPACE_COUNT = len(WHITESPACE_WRAPPERS)

TARGET_SENTIMENT = {"negative": 0.35, "positive": 0.30, "neutral": 0.20, "mixed": 0.15}
MAX_SENTIMENT_DRIFT = 0.08
WOLOF_MARKERS = (
    "dafa baax",
    "dafa metti",
    "dafa jafe",
    "amul solo",
    "lu tax",
    "jërëjëf",
    "waaw",
    "déedéet",
    "yàgg na",
    "ñu ngi sant",
)


@dataclass(eq=False)
class Row:
    text: str
    expected_sentiment: str = ""
    expected_topics: tuple[str, ...] = ()
    noise: str = ""
    source: Row | None = None  # original row of a duplicate / whitespace variant
    id: int = 0


def normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def collect_verbatims(
    client: LlmClient,
    settings: Settings,
    batch_count: int = BATCH_COUNT,
    batch_size: int = BATCH_SIZE,
    min_total: int = MIN_CLEAN_TOTAL,
) -> list[GeneratedVerbatim]:
    """Call Claude batch by batch, dropping duplicates and truncating long texts."""
    system = load_prompt("dataset_system")
    seen: set[str] = set()
    kept: list[GeneratedVerbatim] = []

    def run_batch(batch: int, total: int) -> None:
        result = client.call_tool(
            step=STEP,
            model=settings.dataset_model,
            system=system,
            user=USER_TEMPLATE.format(batch=batch, total=total, count=batch_size),
            tool=RECORD_VERBATIMS,
            max_tokens=MAX_TOKENS,
            effort=settings.dataset_effort,
            cache_system=True,
        )
        added = 0
        for verbatim in result.verbatims:
            text = verbatim.text.strip()
            if len(text) > MAX_CHARS:
                logger.info("batch %d: truncated a %d-char verbatim", batch, len(text))
                text = text[:MAX_CHARS]
            key = normalize(text)
            if not key or key in seen:
                continue
            seen.add(key)
            kept.append(verbatim.model_copy(update={"text": text}))
            added += 1
        logger.info("batch %d/%d: %d received, %d kept", batch, total, len(result.verbatims), added)

    for batch in range(1, batch_count + 1):
        run_batch(batch, batch_count)
    if len(kept) < min_total:
        logger.warning("only %d verbatims (< %d): one complement batch", len(kept), min_total)
        run_batch(batch_count + 1, batch_count + 1)
    return kept


def inject_noise(clean: list[Row], rng: random.Random) -> list[Row]:
    """Return the noise rows (empty, RAS, exact duplicates, whitespace variants)."""
    noise = [Row(text="", noise="empty") for _ in range(EMPTY_COUNT)]
    noise += [Row(text=rng.choice(RAS_VARIANTS), noise="ras") for _ in range(RAS_COUNT)]
    # Distinct originals, so each one has at most one copy.
    originals = rng.sample(clean, DUPLICATE_COUNT + WHITESPACE_COUNT)
    for source in originals[:DUPLICATE_COUNT]:
        noise.append(_copy_of(source, source.text, "duplicate"))
    for source, (before, after) in zip(
        originals[DUPLICATE_COUNT:], WHITESPACE_WRAPPERS, strict=True
    ):
        noise.append(_copy_of(source, f"{before}{source.text}{after}", "whitespace"))
    return noise


def _copy_of(source: Row, text: str, noise: str) -> Row:
    return Row(
        text=text,
        expected_sentiment=source.expected_sentiment,
        expected_topics=source.expected_topics,
        noise=noise,
        source=source,
    )


def shuffle_and_number(rows: list[Row], rng: random.Random) -> list[Row]:
    """Shuffle, keep every original before its copy (as preprocessing expects), assign ids."""
    ordered = rows[:]
    rng.shuffle(ordered)
    position = {id(row): i for i, row in enumerate(ordered)}
    for row in rows:
        if row.source is None:
            continue
        i, j = position[id(row)], position[id(row.source)]
        if i < j:
            ordered[i], ordered[j] = ordered[j], ordered[i]
            position[id(row)], position[id(row.source)] = j, i
    for number, row in enumerate(ordered, start=1):
        row.id = number
    return ordered


def gold_noise(row: Row) -> str:
    if row.noise == "duplicate" and row.source is not None:
        return f"duplicate_of:{row.source.id}"
    return row.noise


def write_outputs(rows: list[Row], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / INPUT_FILE).open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(["id", "verbatim"])
        writer.writerows([row.id, row.text] for row in rows)
    with (out_dir / GOLD_FILE).open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(["id", "expected_sentiment", "expected_topics", "noise"])
        writer.writerows(
            [row.id, row.expected_sentiment, ";".join(row.expected_topics), gold_noise(row)]
            for row in rows
        )


def build_log(client: LlmClient, settings: Settings, rows: list[Row]) -> dict[str, object]:
    costs = [u.cost_usd(PRICING) for u in client.usage]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": settings.dataset_model,
        "effort": settings.dataset_effort,
        "seed": SEED,
        "rows": len(rows),
        "clean_rows": sum(1 for r in rows if not r.noise),
        "calls": [
            {
                "model": u.model,
                "input_tokens": u.input_tokens,
                "cache_creation_tokens": u.cache_creation_tokens,
                "cache_read_tokens": u.cache_read_tokens,
                "output_tokens": u.output_tokens,
                "duration_ms": u.duration_ms,
            }
            for u in client.usage
        ],
        "total_input_tokens": sum(u.input_tokens for u in client.usage),
        "total_cache_creation_tokens": sum(u.cache_creation_tokens for u in client.usage),
        "total_cache_read_tokens": sum(u.cache_read_tokens for u in client.usage),
        "total_output_tokens": sum(u.output_tokens for u in client.usage),
        "estimated_cost_usd": (
            round(sum(c for c in costs if c is not None), 4) if None not in costs else None
        ),
    }


def summarize(rows: list[Row]) -> None:
    """Log the control report: sentiments, topics, noise, lengths, share of Wolof."""
    clean = [r for r in rows if not r.noise]
    sentiments = Counter(r.expected_sentiment for r in clean)
    topics = Counter(t for r in clean for t in r.expected_topics)
    noise = Counter(r.noise for r in rows if r.noise)
    lengths = [len(r.text) for r in clean]
    wolof = sum(1 for r in clean if any(m in r.text.lower() for m in WOLOF_MARKERS))

    logger.info("rows: %d (%d clean, %d noise)", len(rows), len(clean), len(rows) - len(clean))
    for sentiment, target in TARGET_SENTIMENT.items():
        share = sentiments[sentiment] / len(clean)
        logger.info(
            "sentiment %-8s %3d  %4.1f %% (target %d %%)",
            sentiment,
            sentiments[sentiment],
            share * 100,
            target * 100,
        )
        if abs(share - target) > MAX_SENTIMENT_DRIFT:
            logger.warning("sentiment %s drifts more than 8 points from target", sentiment)
    for topic, count in topics.most_common():
        logger.info("topic %-20s %3d", topic, count)
    for kind, count in sorted(noise.items()):
        logger.info("noise %-12s %3d", kind, count)
    logger.info(
        "length (chars): mean %.0f, min %d, max %d",
        statistics.mean(lengths),
        min(lengths),
        max(lengths),
    )
    logger.info("with a wolof marker: %d (%.0f %%)", wolof, wolof / len(clean) * 100)


def generate(
    client: LlmClient,
    settings: Settings,
    out_dir: Path,
    *,
    batch_count: int = BATCH_COUNT,
    batch_size: int = BATCH_SIZE,
    min_total: int = MIN_CLEAN_TOTAL,
) -> list[Row]:
    verbatims = collect_verbatims(client, settings, batch_count, batch_size, min_total)
    clean = [
        Row(
            text=v.text,
            expected_sentiment=v.expected_sentiment,
            expected_topics=tuple(v.expected_topics),
        )
        for v in verbatims
    ]
    rng = random.Random(SEED)
    rows = shuffle_and_number(clean + inject_noise(clean, rng), rng)
    write_outputs(rows, out_dir)
    log = build_log(client, settings, rows)
    (out_dir / LOG_FILE).write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summarize(rows)
    logger.info(
        "%d calls, %d output tokens, estimated cost %s USD",
        len(client.usage),
        log["total_output_tokens"],
        log["estimated_cost_usd"],
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")

    existing = [
        args.out_dir / name
        for name in (INPUT_FILE, GOLD_FILE, LOG_FILE)
        if (args.out_dir / name).exists()
    ]
    if existing and not args.force:
        logger.error("refusing to overwrite %s (use --force)", ", ".join(map(str, existing)))
        return 1

    generate(AnthropicLlmClient(settings), settings, args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
