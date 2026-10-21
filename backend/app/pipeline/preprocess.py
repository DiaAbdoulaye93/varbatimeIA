"""Step 0 - local preprocessing, zero token (IMPLEMENTATION.md §2.1).

Normalizes whitespace, flags empty or non-informative answers, flags exact duplicates
(after normalization) and truncates long texts. Skipped verbatims are never sent to Claude.
"""

import hashlib
import logging
import re
import string
from collections.abc import Sequence

from app.schemas import PreprocessedVerbatim

logger = logging.getLogger(__name__)

MIN_CHARS = 3
MAX_CHARS = 600
SKIPPED_EMPTY = "empty"
DUPLICATE_PREFIX = "duplicate_of:"

# Compared after lowercasing and removing spaces and punctuation ("R.A.S" -> "ras").
NON_INFORMATIVE = frozenset(
    {"ras", "rien", "aucun", "aucune", "néant", "neant", "rienàsignaler", "rienasignaler"}
)

_WHITESPACE = re.compile(r"\s+")
_STRIP_FOR_MATCH = str.maketrans("", "", string.punctuation + string.whitespace)


def normalize(text: str) -> str:
    """Trim and collapse whitespace (spaces, tabs, newlines); case is preserved."""
    return _WHITESPACE.sub(" ", text).strip()


def is_non_informative(text_norm: str) -> bool:
    if len(text_norm) < MIN_CHARS:
        return True
    compact = text_norm.lower().translate(_STRIP_FOR_MATCH)
    return not compact or compact in NON_INFORMATIVE


def dedup_key(text_norm: str) -> str:
    return hashlib.sha256(text_norm.lower().encode("utf-8")).hexdigest()


def preprocess(texts: Sequence[str]) -> list[PreprocessedVerbatim]:
    """Preprocess verbatims in CSV order; idx is the 1-based row position."""
    results: list[PreprocessedVerbatim] = []
    first_idx_by_key: dict[str, int] = {}
    for idx, text in enumerate(texts, start=1):
        text_norm = normalize(text)
        if is_non_informative(text_norm):
            results.append(
                PreprocessedVerbatim(
                    idx=idx, text=text, text_norm=text_norm, skipped_reason=SKIPPED_EMPTY
                )
            )
            continue

        key = dedup_key(text_norm)
        if key in first_idx_by_key:
            results.append(
                PreprocessedVerbatim(
                    idx=idx,
                    text=text,
                    text_norm=text_norm,
                    skipped_reason=f"{DUPLICATE_PREFIX}{first_idx_by_key[key]}",
                )
            )
            continue
        first_idx_by_key[key] = idx

        truncated = len(text_norm) > MAX_CHARS
        if truncated:
            logger.info("verbatim %d truncated from %d to %d chars", idx, len(text_norm), MAX_CHARS)
            text_norm = text_norm[:MAX_CHARS]
        results.append(
            PreprocessedVerbatim(idx=idx, text=text, text_norm=text_norm, truncated=truncated)
        )

    skipped = sum(1 for r in results if r.skipped_reason)
    logger.info(
        "preprocess: %d received, %d kept, %d skipped",
        len(results),
        len(results) - skipped,
        skipped,
    )
    return results
