"""Step 3 - executive synthesis in Markdown.

The model only sees aggregated figures and a few truncated excerpts per theme.
"""

import logging
from collections.abc import Mapping, Sequence

from app.config import Settings
from app.pipeline.cluster import OTHER_LABEL
from app.pipeline.llm_client import LlmClient
from app.pipeline.prompt_loader import load_prompt
from app.schemas import AnalysisStats, SentimentCounts, ThemeResult

logger = logging.getLogger(__name__)

STEP = "synthesize"
MAX_TOKENS = 3_000
EXCERPT_MAX_CHARS = 200
WORD_LIMIT = 500
HEADINGS = ("## Chiffres clés", "## Points forts", "## Points d'attention", "## Recommandations")
NO_EXCERPT_THEMES = frozenset({"appréciation générale", OTHER_LABEL.lower()})
REMINDER = (
    "Rappel : le document commence par `## Chiffres clés` et contient exactement quatre sections."
)

USER_TEMPLATE = """Contexte : {context}

Totaux : {n_received} verbatims reçus, {n_used} exploités, {n_skipped} écartés (vides ou doublons).

Sentiments : {sentiments}.

Thèmes (par effectif décroissant) :

{themes}"""
THEME_TEMPLATE = """### {label} — {count} mentions ({pct} %)
{description}
Sentiments : {sentiments}"""
SENTIMENT_NAMES = {
    "positive": "positif",
    "neutral": "neutre",
    "negative": "négatif",
    "mixed": "mixte",
}


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _sentiments(counts: SentimentCounts, with_counts: bool) -> str:
    total = sum(counts.values())
    parts = []
    for key, name in SENTIMENT_NAMES.items():
        pct = _pct(counts[key], total)
        parts.append(f"{name} {counts[key]} ({pct} %)" if with_counts else f"{name} {pct} %")
    return ", ".join(parts)


def excerpt(text: str) -> str:
    if len(text) <= EXCERPT_MAX_CHARS:
        return text
    return text[: EXCERPT_MAX_CHARS - 1].rstrip() + "…"


def build_user_message(
    context: str,
    stats: AnalysisStats,
    themes: Sequence[ThemeResult],
    texts: Mapping[int, str],
) -> str:
    blocks = []
    for theme in themes:
        block = THEME_TEMPLATE.format(
            label=theme.label,
            count=theme.count,
            pct=_pct(theme.count, stats.n_used),
            description=theme.description,
            sentiments=_sentiments(theme.sentiment_breakdown, with_counts=False),
        )
        if theme.label.lower() not in NO_EXCERPT_THEMES and theme.representative_idx:
            quotes = "\n".join(f"- « {excerpt(texts[i])} »" for i in theme.representative_idx)
            block += f"\nExtraits :\n{quotes}"
        blocks.append(block)
    return USER_TEMPLATE.format(
        context=context,
        n_received=stats.n_received,
        n_used=stats.n_used,
        n_skipped=stats.n_skipped,
        sentiments=_sentiments(stats.sentiment_counts, with_counts=True),
        themes="\n\n".join(blocks),
    )


def is_well_formed(markdown: str) -> bool:
    return markdown.startswith(HEADINGS[0]) and all(h in markdown for h in HEADINGS)


def synthesize(
    client: LlmClient,
    settings: Settings,
    stats: AnalysisStats,
    themes: Sequence[ThemeResult],
    texts: Mapping[int, str],
    context: str,
) -> str:
    user = build_user_message(context, stats, themes, texts)

    def ask(message: str) -> str:
        return client.call_text(
            step=STEP,
            model=settings.synth_model,
            system=load_prompt("synthesize_system"),
            user=message,
            max_tokens=MAX_TOKENS,
            effort=settings.synth_effort,
        )

    markdown = ask(user)
    if not is_well_formed(markdown):
        logger.warning("synthesis does not follow the expected structure, retrying once")
        markdown = ask(f"{user}\n\n{REMINDER}")
        if not is_well_formed(markdown):
            logger.warning("synthesis still malformed after retry, kept as is")
    words = len(markdown.split())
    if words > WORD_LIMIT:
        logger.warning("synthesis is %d words (limit %d)", words, WORD_LIMIT)
    return markdown
