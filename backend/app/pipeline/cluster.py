"""Step 2 - group raw theme labels into canonical themes (IMPLEMENTATION.md §2.3).

One LLM call on the unique raw labels with their frequency; counts, sentiment breakdowns and
representative verbatims are then computed locally, never taken from the model.
"""

import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.config import Settings
from app.pipeline.extract import normalize_label
from app.pipeline.llm_client import LlmClient
from app.pipeline.prompt_loader import load_prompt
from app.schemas import (
    RECORD_THEME_MAPPING,
    ExtractionItem,
    ThemeMapping,
    ThemeResult,
    empty_sentiment_counts,
)

logger = logging.getLogger(__name__)

STEP = "cluster"
MAX_TOKENS = 4_000
MIN_THEMES, MAX_THEMES = 6, 10
OTHER_LABEL = "Autres remarques"
OTHER_DESCRIPTION = "Remarques isolées qui ne se rattachent à aucun autre thème."
OTHER_MAX_SHARE = 0.10
REPRESENTATIVES = 3
USER_TEMPLATE = (
    "Contexte : {context}\nTotal : {total} occurrences, {distinct} libellés distincts.\n\n{lines}"
)


@dataclass
class _Theme:
    label: str
    description: str
    raw_labels: list[str] = field(default_factory=list)


def count_labels(extractions: Mapping[int, ExtractionItem]) -> Counter[str]:
    return Counter(label for item in extractions.values() for label in item.themes)


def build_user_message(context: str, counts: Counter[str]) -> str:
    # Sorted by decreasing count, then alphabetically so the message is deterministic.
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = "\n".join(f"{label} ({count})" for label, count in ordered)
    return USER_TEMPLATE.format(
        context=context, total=sum(counts.values()), distinct=len(counts), lines=lines
    )


def resolve_mapping(mapping: ThemeMapping, counts: Counter[str]) -> list[_Theme]:
    """Assign every raw label to exactly one theme; unmapped labels go to OTHER_LABEL."""
    themes: list[_Theme] = []
    by_label: dict[str, _Theme] = {}
    assigned: set[str] = set()
    for canonical in mapping.themes:
        key = canonical.label.strip().lower()
        theme = by_label.get(key)
        if theme is None:
            theme = _Theme(label=canonical.label.strip(), description=canonical.description)
            by_label[key] = theme
            themes.append(theme)
        for raw in canonical.raw_labels:
            label = normalize_label(raw)
            if label not in counts:
                logger.warning("model returned unknown raw label %r, ignored", raw)
            elif label not in assigned:  # first theme wins on duplicates
                assigned.add(label)
                theme.raw_labels.append(label)

    unmapped = sorted(label for label in counts if label not in assigned)
    if unmapped:
        logger.warning("%d raw labels left unmapped, sent to %r", len(unmapped), OTHER_LABEL)
        other = by_label.get(OTHER_LABEL.lower())
        if other is None:
            other = _Theme(label=OTHER_LABEL, description=OTHER_DESCRIPTION)
            themes.append(other)
        other.raw_labels.extend(unmapped)
    return [t for t in themes if t.raw_labels]


def build_themes(
    themes: list[_Theme],
    extractions: Mapping[int, ExtractionItem],
    texts: Mapping[int, str],
) -> tuple[list[ThemeResult], dict[int, list[int]]]:
    """Compute counts, sentiment breakdowns and representatives; return themes by idx too."""
    theme_of_label = {label: i for i, t in enumerate(themes) for label in t.raw_labels}
    members: list[list[int]] = [[] for _ in themes]
    for idx, item in extractions.items():
        for i in sorted({theme_of_label[label] for label in item.themes}):
            members[i].append(idx)

    order = sorted(
        range(len(themes)),
        key=lambda i: (themes[i].label == OTHER_LABEL, -len(members[i]), themes[i].label),
    )
    results: list[ThemeResult] = []
    theme_ids: dict[int, list[int]] = {idx: [] for idx in extractions}
    for theme_id, i in enumerate(order, start=1):
        breakdown = empty_sentiment_counts()
        for idx in members[i]:
            breakdown[extractions[idx].sentiment] += 1
            theme_ids[idx].append(theme_id)
        # Verbatims carrying a key phrase first, then the shortest ones.
        representatives = sorted(
            members[i], key=lambda idx: (extractions[idx].key_phrase is None, len(texts[idx]), idx)
        )[:REPRESENTATIVES]
        results.append(
            ThemeResult(
                id=theme_id,
                label=themes[i].label,
                description=themes[i].description,
                raw_labels=themes[i].raw_labels,
                count=len(members[i]),
                sentiment_breakdown=breakdown,
                representative_idx=representatives,
            )
        )
    return results, theme_ids


def cluster(
    client: LlmClient,
    settings: Settings,
    extractions: Mapping[int, ExtractionItem],
    texts: Mapping[int, str],
    context: str,
) -> tuple[list[ThemeResult], dict[int, list[int]]]:
    counts = count_labels(extractions)
    if not counts:
        logger.warning("no raw theme to cluster")
        return [], {}
    mapping = client.call_tool(
        step=STEP,
        model=settings.cluster_model,
        system=load_prompt("cluster_system"),
        user=build_user_message(context, counts),
        tool=RECORD_THEME_MAPPING,
        max_tokens=MAX_TOKENS,
        effort=settings.cluster_effort,
    )
    themes, theme_ids = build_themes(resolve_mapping(mapping, counts), extractions, texts)

    if not MIN_THEMES <= len(themes) <= MAX_THEMES:
        logger.warning("%d canonical themes (expected %d-%d)", len(themes), MIN_THEMES, MAX_THEMES)
    other = next((t for t in themes if t.label == OTHER_LABEL), None)
    occurrences = sum(counts.values())
    other_occurrences = sum(counts[label] for label in other.raw_labels) if other else 0
    if other_occurrences > OTHER_MAX_SHARE * occurrences:
        logger.warning("%r holds %d/%d occurrences", OTHER_LABEL, other_occurrences, occurrences)
    return themes, theme_ids
