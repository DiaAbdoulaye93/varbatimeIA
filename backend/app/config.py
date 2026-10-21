"""Application settings, model names and pricing table."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]

Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Bump on any change to a file in app/pipeline/prompts/: it is part of the analysis cache key.
PROMPT_VERSION = "1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: SecretStr | None = None
    llm_max_retries: int = 3

    extract_model: str = "claude-haiku-5-5"
    cluster_model: str = "claude-sonnet-5-5"
    synth_model: str = "claude-sonnet-5-5"
    dataset_model: str = "claude-sonnet-5-5"

    extract_effort: Effort = "low"
    cluster_effort: Effort = "low"
    synth_effort: Effort = "low"
    dataset_effort: Effort = "medium"

    # Models that accept a forced tool_choice; any other model gets tool_choice=auto
    # plus a check that the tool was called (Sonnet 5.5 rejects forcing with a 400).
    forced_tool_choice_models: frozenset[str] = frozenset({"claude-haiku-5-5"})
    # Models sent with server-side refusal fallback (`fallbacks: "default"`).
    server_fallback_models: frozenset[str] = frozenset({"claude-sonnet-5-5"})

    database_url: str = "postgresql+psycopg://postgres@localhost:5432/sat_verbatim"
    test_database_url: str = "postgresql+psycopg://postgres@localhost:5432/sat_verbatim_test"

    log_level: str = "INFO"


@dataclass(frozen=True)
class ModelPricing:
    """USD per million tokens."""

    input: float
    cache_write_5m: float
    cache_read: float
    output: float


# Source: https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-10-21).
# Haiku 5.5 rates are for prompts up to 100,000 tokens; our prompts stay far below that.
PRICING: dict[str, ModelPricing] = {
    "claude-haiku-5-5": ModelPricing(
        input=0.10, cache_write_5m=0.125, cache_read=0.01, output=0.50
    ),
    "claude-sonnet-5-5": ModelPricing(
        input=2.00, cache_write_5m=2.50, cache_read=0.10, output=10.00
    ),
}


@lru_cache
def get_settings() -> Settings:
    return Settings()
