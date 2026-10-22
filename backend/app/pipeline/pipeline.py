"""Run the 4 pipeline steps end to end (used by the CLI and the analysis service)."""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict

from app.config import PRICING, Settings
from app.pipeline.check import check_file
from app.pipeline.cluster import cluster
from app.pipeline.extract import extract
from app.pipeline.llm_client import LlmClient
from app.pipeline.preprocess import DUPLICATE_PREFIX, preprocess
from app.pipeline.synthesize import synthesize
from app.schemas import (
    AnalysisStats,
    ExtractionItem,
    PipelineResult,
    PreprocessedVerbatim,
    ProgressInfo,
    UsageRecord,
    VerbatimResult,
    empty_sentiment_counts,
)

logger = logging.getLogger(__name__)

EXTRACTION_FAILED = "extraction_failed"

# Called with (current_step, progress 0-100, details) whenever the pipeline moves forward.
ProgressCallback = Callable[[str, int, ProgressInfo], None]

# Progress bounds of the extraction step, the longest one.
_EXTRACT_START, _EXTRACT_END = 5, 80


def split_flagged(
    extractions: Mapping[int, ExtractionItem],
) -> tuple[dict[int, ExtractionItem], dict[int, str]]:
    """Separate usable results from those the AI control flagged (off topic, manipulation)."""
    kept = {idx: item for idx, item in extractions.items() if item.flag == "none"}
    flagged = {idx: item.flag for idx, item in extractions.items() if item.flag != "none"}
    if flagged:
        logger.warning("AI control flagged %d verbatims: %s", len(flagged), flagged)
    return kept, flagged


def build_stats(
    preprocessed: Sequence[PreprocessedVerbatim],
    extractions: Mapping[int, ExtractionItem],
    flagged: Mapping[int, str] | None = None,
) -> AnalysisStats:
    counts = empty_sentiment_counts()
    for item in extractions.values():
        counts[item.sentiment] += 1
    n_skipped = sum(1 for p in preprocessed if p.skipped_reason)
    n_flagged = len(flagged or {})
    return AnalysisStats(
        n_received=len(preprocessed),
        n_used=len(extractions),
        n_skipped=n_skipped,
        n_failed=len(preprocessed) - n_skipped - len(extractions) - n_flagged,
        n_flagged=n_flagged,
        sentiment_counts=counts,
    )


def build_verbatim_results(
    preprocessed: Sequence[PreprocessedVerbatim],
    extractions: Mapping[int, ExtractionItem],
    theme_ids: Mapping[int, list[int]],
    flagged: Mapping[int, str] | None = None,
) -> list[VerbatimResult]:
    """One row per CSV line; duplicates inherit the result of their original."""
    flagged = flagged or {}
    results = []
    for p in preprocessed:
        source_idx = p.idx
        if p.skipped_reason and p.skipped_reason.startswith(DUPLICATE_PREFIX):
            source_idx = int(p.skipped_reason.removeprefix(DUPLICATE_PREFIX))
        item = extractions.get(source_idx)
        skipped_reason = p.skipped_reason
        if skipped_reason is None and p.idx in flagged:
            skipped_reason = flagged[p.idx]
        elif skipped_reason is None and item is None:
            skipped_reason = EXTRACTION_FAILED
        results.append(
            VerbatimResult(
                idx=p.idx,
                text=p.text,
                text_norm=p.text_norm,
                skipped_reason=skipped_reason,
                sentiment=item.sentiment if item else None,
                themes_raw=item.themes if item else [],
                key_phrase=item.key_phrase if item else None,
                theme_ids=theme_ids.get(source_idx, []),
            )
        )
    return results


def run_pipeline(
    client: LlmClient,
    settings: Settings,
    texts: Sequence[str],
    context: str,
    on_progress: ProgressCallback | None = None,
) -> PipelineResult:
    start = time.perf_counter()
    first_usage = len(client.usage)

    info = ProgressInfo()

    def notify(step: str, progress: int) -> None:
        logger.info("step %s (%d %%)", step, progress)
        if on_progress is not None:
            on_progress(step, progress, info.model_copy())

    notify("preprocess", 0)
    preprocessed = preprocess(texts)
    kept = [p for p in preprocessed if p.skipped_reason is None]
    norm_texts = {p.idx: p.text_norm for p in preprocessed}
    info.n_kept, info.n_skipped = len(kept), len(preprocessed) - len(kept)
    if kept:
        # Raises InputRejected before any extraction token is spent.
        check_file(client, settings, kept, context)

    notify("extract", _EXTRACT_START)
    span = _EXTRACT_END - _EXTRACT_START

    def on_batch(done: int, total: int) -> None:
        info.batch_done, info.batch_total = done, total
        notify("extract", _EXTRACT_START + span * done // total)

    extractions, flagged = split_flagged(
        extract(client, settings, kept, context, on_progress=on_batch)
    )

    notify("cluster", 85)
    themes, theme_ids = cluster(client, settings, extractions, norm_texts, context)
    stats = build_stats(preprocessed, extractions, flagged)

    notify("synthesize", 92)
    synthesis_md = (
        synthesize(client, settings, stats, themes, norm_texts, context) if themes else ""
    )

    usage = [
        UsageRecord(**asdict(u), cost_usd=u.cost_usd(PRICING)) for u in client.usage[first_usage:]
    ]
    result = PipelineResult(
        context=context,
        stats=stats,
        themes=themes,
        verbatims=build_verbatim_results(preprocessed, extractions, theme_ids, flagged),
        synthesis_md=synthesis_md,
        usage=usage,
        duration_ms=round((time.perf_counter() - start) * 1000),
    )
    notify("done", 100)
    return result
