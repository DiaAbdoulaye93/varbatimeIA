"""File check before analysis: is this really a set of survey answers?

One small Haiku call on an evenly spread sample, so a contract or a code file is rejected
with a clear message before any extraction tokens are spent.
"""

import logging
from collections.abc import Sequence

from app.config import Settings
from app.pipeline.llm_client import LlmClient
from app.pipeline.prompt_loader import load_prompt
from app.schemas import RECORD_FILE_CHECK, PreprocessedVerbatim

logger = logging.getLogger(__name__)

STEP = "check"
SAMPLE_SIZE = 12
SAMPLE_MAX_CHARS = 300
MAX_TOKENS = 400
USER_TEMPLATE = "Contexte annoncé : {context}\n\nÉchantillon ({n} lignes sur {total}) :\n{lines}"


class InputRejected(Exception):
    """The file does not look like survey answers; the message is shown to the user."""


def spread_sample(items: Sequence[PreprocessedVerbatim], size: int) -> list[PreprocessedVerbatim]:
    """Evenly spaced items, so a file that changes content halfway is still noticed."""
    if len(items) <= size:
        return list(items)
    step = len(items) / size
    return [items[int(i * step)] for i in range(size)]


def check_file(
    client: LlmClient,
    settings: Settings,
    verbatims: Sequence[PreprocessedVerbatim],
    context: str,
) -> str:
    """Return the model's description of the file, or raise InputRejected."""
    sample = spread_sample(verbatims, SAMPLE_SIZE)
    lines = "\n".join(f"- {v.text_norm[:SAMPLE_MAX_CHARS]}" for v in sample)
    result = client.call_tool(
        step=STEP,
        model=settings.extract_model,
        system=load_prompt("file_check_system"),
        user=USER_TEMPLATE.format(
            context=context or "non précisé", n=len(sample), total=len(verbatims), lines=lines
        ),
        tool=RECORD_FILE_CHECK,
        max_tokens=MAX_TOKENS,
        effort=settings.extract_effort,
    )
    logger.info("file check: is_survey=%s (%s)", result.is_survey, result.reason)
    if not result.is_survey:
        raise InputRejected(
            result.reason.strip() or "Ce fichier ne semble pas contenir de réponses d'enquête."
        )
    return result.reason
