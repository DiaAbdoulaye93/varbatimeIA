"""Step 1 - batch extraction of sentiment and raw themes."""

import logging
from collections.abc import Callable, Sequence

from app.config import Settings
from app.pipeline.llm_client import LlmClient, LlmError
from app.pipeline.prompt_loader import load_prompt
from app.schemas import RECORD_EXTRACTION, ExtractionItem, PreprocessedVerbatim

logger = logging.getLogger(__name__)

STEP = "extract"
BATCH_SIZE = 25
RETRY_BATCH_SIZE = 10
MAX_TOKENS = 2_000
MAX_THEMES = 3
KEY_PHRASE_MAX_CHARS = 80
FALLBACK_THEME = "appréciation générale"
USER_TEMPLATE = "Contexte de l'enquête : {context}\n\nVerbatims :\n{lines}"

# Called after each batch with (batches_done, batches_total).
ProgressCallback = Callable[[int, int], None]


def normalize_label(label: str) -> str:
    return " ".join(label.split()).lower().rstrip(" .;,")


def build_user_message(context: str, batch: Sequence[PreprocessedVerbatim]) -> str:
    lines = "\n".join(f"{v.idx}: {v.text_norm}" for v in batch)
    return USER_TEMPLATE.format(context=context, lines=lines)


def clean_item(item: ExtractionItem) -> ExtractionItem:
    """Normalize labels, enforce 1-3 distinct themes and the key phrase length."""
    themes = list(dict.fromkeys(t for t in map(normalize_label, item.themes) if t))
    if len(themes) > MAX_THEMES:
        logger.warning("verbatim %d: %d themes, keeping %d", item.idx, len(themes), MAX_THEMES)
        themes = themes[:MAX_THEMES]
    key_phrase = (item.key_phrase or "").strip()[:KEY_PHRASE_MAX_CHARS] or None
    return item.model_copy(update={"themes": themes or [FALLBACK_THEME], "key_phrase": key_phrase})


def _chunks[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def extract(
    client: LlmClient,
    settings: Settings,
    verbatims: Sequence[PreprocessedVerbatim],
    context: str,
    on_progress: ProgressCallback | None = None,
) -> dict[int, ExtractionItem]:
    """Return one cleaned result per idx; idx absent from the result failed extraction.

    Batches run sequentially on purpose: the cached system prompt is written by the first
    call and read by every following one.
    """
    system = load_prompt("extract_system")
    results: dict[int, ExtractionItem] = {}

    def run(batch: Sequence[PreprocessedVerbatim]) -> None:
        expected = {v.idx for v in batch}
        try:
            output = client.call_tool(
                step=STEP,
                model=settings.extract_model,
                system=system,
                user=build_user_message(context, batch),
                tool=RECORD_EXTRACTION,
                max_tokens=MAX_TOKENS,
                effort=settings.extract_effort,
                cache_system=True,
            )
        except LlmError as exc:
            logger.warning("extraction batch failed, %d verbatims to retry: %s", len(batch), exc)
            return
        for item in output.results:
            if item.idx not in expected:
                logger.warning("ignoring result for unknown idx %d", item.idx)
                continue
            results.setdefault(item.idx, clean_item(item))

    batches = _chunks(verbatims, BATCH_SIZE)
    for done, batch in enumerate(batches, start=1):
        run(batch)
        if on_progress is not None:
            on_progress(done, len(batches))

    missing = [v for v in verbatims if v.idx not in results]
    if missing:
        logger.warning("%d verbatims missing after extraction, retrying once", len(missing))
        for batch in _chunks(missing, RETRY_BATCH_SIZE):
            run(batch)
    failed = [v.idx for v in verbatims if v.idx not in results]
    if failed:
        logger.warning("extraction failed for idx %s", failed)
    return results
