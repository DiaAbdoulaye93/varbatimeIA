"""Single entry point for Claude API calls.

No other module imports `anthropic`. Every call records its usage (tokens, model, duration,
pipeline step) in `client.usage`; tests inject a fake implementing `LlmClient`.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic
from anthropic.types import Message
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel, ValidationError

from app.config import Effort, ModelPricing, Settings
from app.schemas import ToolSpec

logger = logging.getLogger(__name__)

SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# JSON Schema keywords that strict tool use does not support. They are removed from the
# schema sent to the API; Pydantic still enforces them when validating the tool input.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "title",
        "default",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
    }
)
# Keys whose children are names (field names, definition names), not schema keywords.
_NAME_MAPPING_KEYS = frozenset({"properties", "$defs"})


class LlmError(RuntimeError):
    """A Claude call failed for good (API error, refusal, missing or invalid tool call).

    The message is shown to the user (French); technical details go to the logs.
    """


TRUNCATED_MESSAGE = "la réponse du modèle a dépassé la longueur maximale autorisée"
UNUSABLE_MESSAGE = "le modèle n'a pas renvoyé de résultat exploitable"
REFUSAL_MESSAGE = "le modèle a refusé de traiter ce contenu"
CONNECTION_MESSAGE = "impossible de joindre le service Claude (problème de connexion)"


def _status_message(status_code: int) -> str:
    if status_code in (401, 403):
        return "la clé API Anthropic est invalide ou n'a pas les droits nécessaires"
    if status_code == 429:
        return "la limite de débit de l'API Claude est atteinte, réessayez dans quelques minutes"
    if status_code >= 500:
        return "le service Claude est momentanément indisponible ou surchargé, réessayez plus tard"
    return f"le service Claude a renvoyé une erreur (code {status_code})"


@dataclass(frozen=True)
class LlmUsage:
    step: str
    model: str
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    duration_ms: int

    def cost_usd(self, pricing: dict[str, ModelPricing]) -> float | None:
        price = pricing.get(self.model)
        if price is None:
            return None
        return price.cost(
            self.input_tokens,
            self.cache_creation_tokens,
            self.cache_read_tokens,
            self.output_tokens,
        )


class LlmClient(Protocol):
    usage: list[LlmUsage]

    def call_tool[T: BaseModel](
        self,
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        tool: ToolSpec[T],
        max_tokens: int,
        effort: Effort,
        cache_system: bool = False,
    ) -> T: ...

    def call_text(
        self,
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        effort: Effort,
        cache_system: bool = False,
    ) -> str: ...


def to_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema of a Pydantic model, reduced to what strict tool use accepts."""
    return _clean_schema(model.model_json_schema())


def _clean_schema(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_SCHEMA_KEYS:
            continue
        if key in _NAME_MAPPING_KEYS:
            cleaned[key] = {name: _clean_schema(child) for name, child in value.items()}
        else:
            cleaned[key] = _clean_schema(value)
    if cleaned.get("type") == "object":
        cleaned["additionalProperties"] = False
    return cleaned


class AnthropicLlmClient:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        if client is None:
            if settings.anthropic_api_key is None:
                raise LlmError("ANTHROPIC_API_KEY is not set (backend/.env)")
            client = anthropic.Anthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                max_retries=settings.llm_max_retries,
            )
        self._client = client
        self._settings = settings
        self.usage: list[LlmUsage] = []

    def call_tool[T: BaseModel](
        self,
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        tool: ToolSpec[T],
        max_tokens: int,
        effort: Effort,
        cache_system: bool = False,
    ) -> T:
        forced = model in self._settings.forced_tool_choice_models
        tool_choice = {"type": "tool", "name": tool.name} if forced else {"type": "auto"}
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": to_strict_schema(tool.input_model),
                "strict": True,
            }
        ]
        error = ""
        # tool_choice=auto does not guarantee a call: allow one more attempt.
        for attempt in (1, 2):
            response = self._create(
                step=step,
                model=model,
                system=system,
                user=user,
                max_tokens=max_tokens,
                effort=effort,
                cache_system=cache_system,
                tools=tools,
                tool_choice=tool_choice,
            )
            if response.stop_reason == "max_tokens":
                # The same request would be cut at the same place: do not retry it.
                logger.error("%s: tool input truncated at max_tokens=%d", step, max_tokens)
                raise LlmError(TRUNCATED_MESSAGE)
            block = next(
                (b for b in response.content if b.type == "tool_use" and b.name == tool.name),
                None,
            )
            if block is None:
                error = f"no {tool.name} call (stop_reason={response.stop_reason})"
            else:
                try:
                    return tool.input_model.model_validate(block.input)
                except ValidationError as exc:
                    error = f"invalid {tool.name} input ({exc.error_count()} errors): {exc}"
            logger.warning("%s: attempt %d failed: %s", step, attempt, error)
        logger.error("%s: giving up: %s", step, error)
        raise LlmError(UNUSABLE_MESSAGE)

    def call_text(
        self,
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        effort: Effort,
        cache_system: bool = False,
    ) -> str:
        response = self._create(
            step=step,
            model=model,
            system=system,
            user=user,
            max_tokens=max_tokens,
            effort=effort,
            cache_system=cache_system,
        )
        # Read by block type: adaptive thinking may put thinking blocks first.
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def _create(
        self,
        *,
        step: str,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        effort: Effort,
        cache_system: bool,
        **extra: Any,
    ) -> Message | BetaMessage:
        system_block: dict[str, Any] = {"type": "text", "text": system}
        if cache_system:
            system_block["cache_control"] = {"type": "ephemeral"}
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [system_block],
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": effort},
            **extra,
        }
        start = time.perf_counter()
        try:
            if model in self._settings.server_fallback_models:
                response = self._client.beta.messages.create(
                    betas=[SERVER_FALLBACK_BETA], fallbacks="default", **params
                )
            else:
                response = self._client.messages.create(**params)
        except anthropic.APIStatusError as exc:
            logger.error("%s: API error %d: %s", step, exc.status_code, exc.message)
            raise LlmError(_status_message(exc.status_code)) from exc
        except anthropic.APIConnectionError as exc:
            logger.error("%s: connection error: %s", step, exc)
            raise LlmError(CONNECTION_MESSAGE) from exc
        duration_ms = round((time.perf_counter() - start) * 1000)
        self._record(step, response, duration_ms)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            logger.error("%s: refusal (category=%s)", step, getattr(details, "category", None))
            raise LlmError(REFUSAL_MESSAGE)
        if response.stop_reason == "max_tokens":
            logger.warning("%s: response hit max_tokens=%d", step, max_tokens)
        return response

    def _record(self, step: str, response: Message | BetaMessage, duration_ms: int) -> None:
        usage = response.usage
        entry = LlmUsage(
            step=step,
            model=response.model,
            input_tokens=usage.input_tokens,
            cache_creation_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            output_tokens=usage.output_tokens,
            duration_ms=duration_ms,
        )
        self.usage.append(entry)
        logger.info(
            "%s: model=%s in=%d cache_write=%d cache_read=%d out=%d %dms",
            step,
            entry.model,
            entry.input_tokens,
            entry.cache_creation_tokens,
            entry.cache_read_tokens,
            entry.output_tokens,
            duration_ms,
        )
