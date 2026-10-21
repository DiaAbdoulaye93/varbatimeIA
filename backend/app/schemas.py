"""Pydantic schemas shared by the pipeline and the API.

Tool input schemas are defined once here: llm_client derives the JSON schema sent to the
API from these models and re-validates every tool input against them.
"""

from dataclasses import dataclass
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
