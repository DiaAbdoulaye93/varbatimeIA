"""Pydantic schemas shared by the pipeline and the API.

Tool input schemas are defined once here: llm_client derives the JSON schema sent to the
API from these models and re-validates every tool input against them.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Sentiment = Literal["positive", "neutral", "negative", "mixed"]
Topic = Literal[
    "reseau",
    "service_client",
    "tarif_mobile_money",
    "tarif_forfait",
    "application",
    "agence",
    "delai",
    "general",
]


class StrictModel(BaseModel):
    # extra="forbid" emits additionalProperties: false, required by strict tool use.
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolSpec[T: BaseModel]:
    name: str
    description: str
    input_model: type[T]


# --- Preprocessing (app/pipeline/preprocess.py) ---


class PreprocessedVerbatim(BaseModel):
    idx: int  # 1-based position of the row in the CSV
    text: str  # raw text as received
    text_norm: str  # normalized (and possibly truncated) text sent to the LLM
    skipped_reason: str | None = None  # "empty" | "duplicate_of:<idx>" | None
    truncated: bool = False


# --- Extraction tool (app/pipeline/extract.py) ---
# Bounds such as "1 to 3 themes" are enforced in extract.py rather than in the schema, so
# that one off-spec item does not invalidate a whole batch of 25.


class ExtractionItem(StrictModel):
    idx: int
    sentiment: Sentiment
    themes: list[str] = Field(description="1 to 3 short lowercase French labels")
    key_phrase: str | None = Field(
        default=None, description="Optional verbatim excerpt, 8 words max, copied as is"
    )


class ExtractionBatch(StrictModel):
    results: list[ExtractionItem]


RECORD_EXTRACTION = ToolSpec(
    name="record_extraction",
    description="Record sentiment and themes for every verbatim in the batch.",
    input_model=ExtractionBatch,
)


# --- Theme clustering tool (app/pipeline/cluster.py) ---


class CanonicalTheme(StrictModel):
    label: str
    description: str
    raw_labels: list[str] = Field(description="Raw labels copied exactly as received")


class ThemeMapping(StrictModel):
    themes: list[CanonicalTheme] = Field(description="6 to 10 canonical themes")


RECORD_THEME_MAPPING = ToolSpec(
    name="record_theme_mapping",
    description=(
        "Record the final coding grid: canonical themes and the raw labels each one absorbs."
    ),
    input_model=ThemeMapping,
)


# --- Pipeline results (CLI output, API responses) ---

SentimentCounts = dict[Sentiment, int]


def empty_sentiment_counts() -> SentimentCounts:
    return {"positive": 0, "neutral": 0, "negative": 0, "mixed": 0}


class VerbatimResult(BaseModel):
    idx: int
    text: str
    text_norm: str
    skipped_reason: str | None = None  # empty | duplicate_of:<idx> | extraction_failed
    sentiment: Sentiment | None = None
    themes_raw: list[str] = []
    key_phrase: str | None = None
    theme_ids: list[int] = []


class ThemeResult(BaseModel):
    id: int  # 1-based rank, by decreasing count
    label: str
    description: str
    raw_labels: list[str]
    count: int  # verbatims mentioning the theme
    sentiment_breakdown: SentimentCounts
    representative_idx: list[int]


class AnalysisStats(BaseModel):
    n_received: int
    n_used: int  # verbatims with an extraction result
    n_skipped: int  # empty or duplicate, never sent to the LLM
    n_failed: int  # sent but no valid extraction result
    sentiment_counts: SentimentCounts


class UsageRecord(BaseModel):
    step: str
    model: str
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    duration_ms: int
    cost_usd: float | None


class PipelineResult(BaseModel):
    context: str
    stats: AnalysisStats
    themes: list[ThemeResult]
    verbatims: list[VerbatimResult]
    synthesis_md: str
    usage: list[UsageRecord]
    duration_ms: int


# --- API I/O (app/api/analyses.py), mirrored by frontend/src/app/core/models.ts ---

AnalysisStatus = Literal["pending", "processing", "done", "failed"]


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class AnalysisCreated(BaseModel):
    id: str
    status: AnalysisStatus
    cached: bool  # true when an identical analysis was reused instead of re-running


class AnalysisSummary(BaseModel):
    id: str
    name: str
    status: AnalysisStatus
    progress: int
    created_at: datetime
    total_verbatims: int


class AnalysisDetail(AnalysisSummary):
    context: str
    current_step: str
    error: str | None
    stats: AnalysisStats | None
    synthesis_md: str | None
    duration_ms: int | None
    finished_at: datetime | None


class RepresentativeVerbatim(BaseModel):
    idx: int
    text: str


class ThemeOut(BaseModel):
    id: int
    rank: int
    label: str
    description: str
    count: int
    pct: int  # share of analysed verbatims, rounded
    sentiment_breakdown: SentimentCounts
    raw_labels: list[str]
    representatives: list[RepresentativeVerbatim]


class VerbatimOut(BaseModel):
    idx: int
    text: str
    sentiment: Sentiment | None
    themes_raw: list[str]
    key_phrase: str | None
    skipped_reason: str | None
    theme_ids: list[int]


class VerbatimPage(BaseModel):
    items: list[VerbatimOut]
    total: int
    page: int
    size: int


class StepUsage(BaseModel):
    step: str
    calls: int
    models: list[str]
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    duration_ms: int
    cost_usd: float | None


class UsageOut(BaseModel):
    steps: list[StepUsage]
    total: StepUsage
    analysis_duration_ms: int | None


# --- Dataset generation (scripts/generate_dataset.py) ---


class GeneratedVerbatim(StrictModel):
    text: str
    expected_sentiment: Sentiment
    expected_topics: list[Topic] = Field(min_length=1, max_length=2)


class VerbatimBatch(StrictModel):
    verbatims: list[GeneratedVerbatim]


RECORD_VERBATIMS = ToolSpec(
    name="record_verbatims",
    description="Record the generated survey verbatims with their reference labels.",
    input_model=VerbatimBatch,
)
