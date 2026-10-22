"""Run the full pipeline on a CSV outside the API (debug, README figures).

Usage (from backend/):
  uv run python scripts/run_pipeline_cli.py ../data/samples/telecom_satisfaction_200.csv \
      [--context "..."] [--out ../out/result.json] [--gold ../data/samples/...gold.csv]
"""

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from app.config import get_settings
from app.pipeline.llm_client import AnthropicLlmClient, LlmError
from app.pipeline.pipeline import run_pipeline
from app.schemas import PipelineResult
from app.services.file_loader import FileError, load_verbatims

logger = logging.getLogger("run_pipeline_cli")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "out" / "result.json"
TOPIC_MAPPING = REPO_ROOT / "data" / "samples" / "topic_mapping.json"
DEFAULT_CONTEXT = (
    "Enquête de satisfaction clients, opérateur télécom et mobile money, "
    "Dakar et régions, septembre 2026."
)
POLAR = frozenset({"positive", "negative"})


def log_recap(result: PipelineResult) -> None:
    by_step: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    total_cost = 0.0
    for u in result.usage:
        row = by_step[u.step]
        row[0] += 1
        row[1] += u.input_tokens
        row[2] += u.cache_creation_tokens
        row[3] += u.cache_read_tokens
        row[4] += u.output_tokens
        row[5] += u.duration_ms
        total_cost += u.cost_usd or 0.0
    logger.info(
        "%-11s %5s %8s %9s %9s %8s %8s", "step", "calls", "in", "cache_w", "cache_r", "out", "ms"
    )
    for step, (calls, inp, cw, cr, out, ms) in by_step.items():
        logger.info("%-11s %5d %8d %9d %9d %8d %8d", step, calls, inp, cw, cr, out, ms)
    stats = result.stats
    logger.info(
        "%d verbatims: %d analysed, %d skipped, %d failed | %d themes | %d calls, %.4f USD, %.0f s",
        stats.n_received,
        stats.n_used,
        stats.n_skipped,
        stats.n_failed,
        len(result.themes),
        len(result.usage),
        total_cost,
        result.duration_ms / 1000,
    )
    if any(u.cost_usd is None for u in result.usage):
        logger.warning("some calls used a model missing from the pricing table")


def evaluate_against_gold(result: PipelineResult, gold_path: Path) -> None:
    """Sentiment agreement, noise detection and (if mapped) topic coverage vs gold labels."""
    with gold_path.open(encoding="utf-8", newline="") as f:
        gold = {int(row["id"]): row for row in csv.DictReader(f)}

    exact = relaxed = compared = 0
    noise_ok = noise_total = 0
    for v in result.verbatims:
        expected = gold[v.idx]
        if expected["noise"]:
            noise_total += 1
            want = expected["noise"]
            if want.startswith("duplicate_of:"):
                noise_ok += v.skipped_reason == want
            elif want == "whitespace":
                noise_ok += (v.skipped_reason or "").startswith("duplicate_of:")
            else:
                noise_ok += v.skipped_reason == "empty"
        elif v.sentiment is not None:
            compared += 1
            exp, got = expected["expected_sentiment"], v.sentiment
            exact += exp == got
            # "mixed" is the most debatable class: count it as agreeing with a polar label.
            relaxed += exp == got or ({exp, got} - POLAR) == {"mixed"}
    logger.info(
        "gold: sentiment %.0f %% exact, %.0f %% with mixed merged (%d verbatims)",
        100 * exact / compared,
        100 * relaxed / compared,
        compared,
    )
    logger.info("gold: noise %d/%d rows correctly skipped", noise_ok, noise_total)

    if not TOPIC_MAPPING.exists():
        logger.info("gold: no %s, topic coverage skipped", TOPIC_MAPPING.name)
        return
    mapping: dict[str, list[str]] = json.loads(TOPIC_MAPPING.read_text(encoding="utf-8"))
    labels = {t.id: t.label for t in result.themes}
    for topic, theme_labels in mapping.items():
        rows = [
            v
            for v in result.verbatims
            if not gold[v.idx]["noise"]
            and topic in gold[v.idx]["expected_topics"].split(";")
            and v.sentiment is not None
        ]
        hit = sum(1 for v in rows if {labels[i] for i in v.theme_ids} & set(theme_labels))
        if rows:
            logger.info(
                "gold: topic %-20s %3.0f %% covered (%d)", topic, 100 * hit / len(rows), len(rows)
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--gold", type=Path, help="reference labels (.gold.csv) to compare with")
    parser.add_argument(
        "--result",
        type=Path,
        help="evaluate an existing result.json instead of running the pipeline (no API call)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    if args.result:
        result = PipelineResult.model_validate_json(args.result.read_text(encoding="utf-8"))
        log_recap(result)
        if args.gold:
            evaluate_against_gold(result, args.gold)
        return 0

    try:
        texts = load_verbatims(args.csv.read_bytes(), args.csv.name).texts
        result = run_pipeline(AnthropicLlmClient(settings), settings, texts, args.context)
    except (FileError, LlmError, OSError) as exc:
        logger.error("%s", exc)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    logger.info("result written to %s", args.out)
    log_recap(result)
    if args.gold:
        evaluate_against_gold(result, args.gold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
