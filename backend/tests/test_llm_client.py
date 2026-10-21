"""AnthropicLlmClient against a stubbed SDK client: request shape, retries, usage."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.config import PRICING, Settings
from app.pipeline.llm_client import (
    SERVER_FALLBACK_BETA,
    AnthropicLlmClient,
    LlmError,
    LlmUsage,
    to_strict_schema,
)
from app.schemas import RECORD_VERBATIMS, VerbatimBatch

VALID_INPUT = {
    "verbatims": [
        {"text": "réseau nul", "expected_sentiment": "negative", "expected_topics": ["reseau"]}
    ]
}


def make_response(
    content: list[Any], stop_reason: str = "tool_use", model: str = "claude-haiku-5-5"
) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        model=model,
        usage=SimpleNamespace(
            input_tokens=120,
            cache_creation_input_tokens=2000,
            cache_read_input_tokens=None,
            output_tokens=80,
        ),
    )


def tool_block(payload: dict[str, Any], name: str = "record_verbatims") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=payload)


class StubMessages:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    def create(self, **params: Any) -> SimpleNamespace:
        self.requests.append(params)
        return self._responses.pop(0)


class StubAnthropic:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.messages = StubMessages(responses)
        self.beta = SimpleNamespace(messages=self.messages)


def make_client(responses: list[SimpleNamespace]) -> tuple[AnthropicLlmClient, StubMessages]:
    stub = StubAnthropic(responses)
    return AnthropicLlmClient(Settings(), client=stub), stub.messages  # type: ignore[arg-type]


def call(client: AnthropicLlmClient, model: str = "claude-haiku-5-5") -> VerbatimBatch:
    return client.call_tool(
        step="dataset",
        model=model,
        system="SYSTEM",
        user="USER",
        tool=RECORD_VERBATIMS,
        max_tokens=1000,
        effort="low",
        cache_system=True,
    )


def test_strict_schema_drops_unsupported_keywords() -> None:
    schema = to_strict_schema(VerbatimBatch)
    dumped = str(schema)
    assert "maxItems" not in dumped and "minItems" not in dumped and "title" not in dumped
    item = schema["$defs"]["GeneratedVerbatim"]
    assert item["additionalProperties"] is False
    assert schema["additionalProperties"] is False
    assert set(item["required"]) == {"text", "expected_sentiment", "expected_topics"}


def test_haiku_forces_the_tool_and_caches_the_system_prompt() -> None:
    client, messages = make_client([make_response([tool_block(VALID_INPUT)])])
    result = call(client)
    assert result.verbatims[0].expected_topics == ["reseau"]
    request = messages.requests[0]
    assert request["tool_choice"] == {"type": "tool", "name": "record_verbatims"}
    assert request["tools"][0]["strict"] is True
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["output_config"] == {"effort": "low"}
    assert "temperature" not in request and "fallbacks" not in request


def test_sonnet_uses_auto_choice_and_server_fallback() -> None:
    response = make_response([tool_block(VALID_INPUT)], model="claude-sonnet-5-5")
    client, messages = make_client([response])
    call(client, model="claude-sonnet-5-5")
    request = messages.requests[0]
    assert request["tool_choice"] == {"type": "auto"}
    assert request["fallbacks"] == "default"
    assert request["betas"] == [SERVER_FALLBACK_BETA]


def test_retries_once_when_the_tool_is_not_called() -> None:
    text_only = make_response([SimpleNamespace(type="text", text="hello")], "end_turn")
    client, messages = make_client([text_only, make_response([tool_block(VALID_INPUT)])])
    assert len(call(client, model="claude-sonnet-5-5").verbatims) == 1
    assert len(messages.requests) == 2
    assert len(client.usage) == 2


def test_raises_after_two_invalid_tool_inputs() -> None:
    bad = {"verbatims": [{"text": "x", "expected_sentiment": "angry", "expected_topics": []}]}
    responses = [make_response([tool_block(bad)]), make_response([tool_block(bad)])]
    client, _ = make_client(responses)
    with pytest.raises(LlmError, match="invalid record_verbatims input"):
        call(client)


def test_refusal_raises_without_retry() -> None:
    refusal = make_response([], stop_reason="refusal")
    refusal.stop_details = SimpleNamespace(category="cyber")
    client, messages = make_client([refusal])
    with pytest.raises(LlmError, match="refused"):
        call(client)
    assert len(messages.requests) == 1


def test_usage_is_recorded_and_priced() -> None:
    client, _ = make_client([make_response([tool_block(VALID_INPUT)])])
    call(client)
    usage = client.usage[0]
    assert usage == LlmUsage(
        step="dataset",
        model="claude-haiku-5-5",
        input_tokens=120,
        cache_creation_tokens=2000,
        cache_read_tokens=0,
        output_tokens=80,
        duration_ms=usage.duration_ms,
    )
    expected = (120 * 0.10 + 2000 * 0.125 + 80 * 0.50) / 1_000_000
    assert usage.cost_usd(PRICING) == pytest.approx(expected)


def test_call_text_reads_text_blocks_only() -> None:
    blocks = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text="## Chiffres clés\n..."),
    ]
    client, _ = make_client([make_response(blocks, stop_reason="end_turn")])
    text = client.call_text(
        step="synthesize",
        model="claude-haiku-5-5",
        system="S",
        user="U",
        max_tokens=100,
        effort="low",
    )
    assert text == "## Chiffres clés\n..."
