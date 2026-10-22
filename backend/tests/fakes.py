"""Test doubles: no test ever reaches the Claude API."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.config import Effort
from app.pipeline.llm_client import LlmUsage
from app.schemas import ToolSpec

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
# Canned answer of the file check (app/pipeline/check.py): the file is a survey.
SURVEY_OK = {"is_survey": True, "reason": "Avis de clients sur un opérateur télécom."}

# A canned tool input, or a function building it from the user message.
# A function may raise LlmError to simulate a failed call.
Payload = dict[str, Any] | Callable[[str], dict[str, Any]]


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def load_text_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class FakeLlmClient:
    """Return canned tool inputs (keyed by tool name) and canned texts, in order.

    The last payload of each queue is repeated once the queue is exhausted.
    """

    def __init__(
        self,
        tool_payloads: dict[str, list[Payload]] | None = None,
        texts: list[str] | None = None,
    ) -> None:
        self._tool_payloads = tool_payloads or {}
        self._texts = texts or []
        self.calls: list[dict[str, Any]] = []
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
        queue = self._tool_payloads[tool.name]
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        self._record(step, model, user)
        if callable(payload):
            payload = payload(user)
        return tool.input_model.model_validate(payload)

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
        text = self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        self._record(step, model, user)
        return text

    def _record(self, step: str, model: str, user: str) -> None:
        self.calls.append({"step": step, "model": model, "user": user})
        self.usage.append(
            LlmUsage(
                step=step,
                model=model,
                input_tokens=100,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                output_tokens=50,
                duration_ms=1,
            )
        )
