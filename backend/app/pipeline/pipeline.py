"""Run the 4 pipeline steps end to end (used by the CLI and the analysis service)."""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict

from app.config import PRICING, Settings
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
    UsageRecord,
    VerbatimResult,
    empty_sentiment_counts,
)

logger = logging.getLogger(__name__)

EXTRACTION_FAILED = "extraction_failed"

# Called with (current_step, progress 0-100) whenever the pipeline moves forward.
ProgressCallback = Callable[[str, int], None]

# Progress bounds of the extraction step, the longest one.
_EXTRACT_START, _EXTRACT_END = 5, 80


def build_stats(
    preprocessed: Sequence[PreprocessedVerbatim], extractions: Mapping[int, ExtractionItem]
) -> AnalysisStats:
    counts = empty_sentiment_counts()
    for item in extractions.values():
        counts[item.sentiment] += 1
    n_skipped = sum(1 for p in preprocessed if p.skipped_reason)
    return AnalysisStats(
        n_received=len(preprocessed),
        n_used=len(extractions),
        n_skipped=n_skipped,
        n_failed=len(preprocessed) - n_skipped - len(extractions),
        sentiment_counts=counts,
    )


def build_verbatim_results(
    preprocessed: Sequence[PreprocessedVerbatim],
    extractions: Mapping[int, ExtractionItem],
    theme_ids: Mapping[int, list[int]],
) -> list[VerbatimResult]:
    """One row per CSV line; duplicates inherit the result of their original."""
    results = []
    for p in preprocessed:
        source_idx = p.idx
        if p.skipped_reason and p.skipped_reason.startswith(DUPLICATE_PREFIX):
            source_idx = int(p.skipped_reason.removeprefix(DUPLICATE_PREFIX))
        item = extractions.get(source_idx)
        skipped_reason = p.skipped_reason
        if skipped_reason is None and item is None:
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

    def notify(step: str, progress: int) -> None:
        logger.info("step %s (%d %%)", step, progress)
        if on_progress is not None:
            on_progress(step, progress)

    notify("preprocess", 0)
    preprocessed = preprocess(texts)
    kept = [p for p in preprocessed if p.skipped_reason is None]
    norm_texts = {p.idx: p.text_norm for p in preprocessed}

    notify("extract", _EXTRACT_START)
    span = _EXTRACT_END - _EXTRACT_START
    extractions = extract(
        client,
        settings,
        kept,
        context,
        on_progress=lambda done, total: notify("extract", _EXTRACT_START + span * done // total),
    )

    notify("cluster", 85)
    themes, theme_ids = cluster(client, settings, extractions, norm_texts, context)
    stats = build_stats(preprocessed, extractions)

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
        verbatims=build_verbatim_results(preprocessed, extractions, theme_ids),
        synthesis_md=synthesis_md,
        usage=usage,
        duration_ms=round((time.perf_counter() - start) * 1000),
    )
    notify("done", 100)
    return result
