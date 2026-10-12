"""Anthropic adapter: the pause_turn continuation loop (design.md §6.1). SDK mocked, no cost."""
import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from anthropic.types.beta import BetaMessage

from providers.anthropic_provider import MAX_CONTINUATIONS, AnthropicProvider, block_param
from providers.base import ModelResponse, ToolStep, UsageMeter
from providers.errors import ProviderRefusalError
from tests.test_anthropic_provider import HISTORY, MODEL, FakeStream, collect, make_message
from tests.test_anthropic_tools import ALL_TOOLS, CODE_RESULT, CODE_USE

THINKING = {"type": "thinking", "thinking": "", "signature": "c2lnbmF0dXJl"}


def paused(*content: dict[str, Any], container: str | None = "container_1", **usage: int) -> BetaMessage:
    extra: dict[str, Any] = {"container": {"id": container, "expires_at": "2026-11-12T00:00:00Z"}} if container else {}
    message = make_message(content=list(content), stop_reason="pause_turn", **extra)
    if usage:
        message.usage = message.usage.model_copy(update=usage)
    return message


class SequenceMessages:
    """Stands in for client.beta.messages: each request gets the next scripted response."""

    def __init__(self, responses: list[BetaMessage]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> BetaMessage:
        self.requests.append(kwargs)
        return self.responses.pop(0)

    def stream(self, **kwargs: Any) -> FakeStream:
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        text = [b.text for b in response.content if b.type == "text"]
        tools = [b for b in response.content if b.type != "text" and b.type != "thinking"]
        chunks: list[str | None] = [*[None] * len(tools), *text]
        return FakeStream(chunks, response, blocks=tools)


def provider_for(responses: list[BetaMessage]) -> tuple[AnthropicProvider, SequenceMessages]:
    messages = SequenceMessages(responses)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return AnthropicProvider(api_key="unused", model=MODEL, client=client), messages


FIRST = paused(THINKING, {"type": "text", "text": "Working on it."}, CODE_USE)
DONE = make_message([CODE_RESULT, {"type": "text", "text": "The answer is 2^100."}])


def test_a_paused_turn_is_continued_with_the_paused_content():
    provider, fake = provider_for([FIRST, DONE])
    reply = asyncio.run(provider.generate(HISTORY, "sys", tools=ALL_TOOLS))

    assert len(fake.requests) == 2
    first, second = fake.requests
    assert second["messages"][:-1] == first["messages"]  # same conversation…
    added = second["messages"][-1]
    assert added["role"] == "assistant"  # …plus the paused reply; no "continue" user message
    assert [b["type"] for b in added["content"]] == ["thinking", "text", "server_tool_use"]
    assert added["content"][0]["signature"] == "c2lnbmF0dXJl"  # thinking passed back unchanged
    assert second["container"] == "container_1"  # the code sandbox carries over
    assert "container" not in first
    for key in ("tools", "system", "model", "max_tokens"):
        assert second[key] == first[key]

    assert reply.requests == 2
    assert reply.stop_reason == "end_turn"
    assert reply.text == "Working on it.\n\nThe answer is 2^100."


def test_usage_is_summed_across_requests():
    first = paused({"type": "text", "text": "a"}, input_tokens=100, output_tokens=20, cache_read_input_tokens=500)
    done = make_message([{"type": "text", "text": "b"}])  # 30 in, 4 out
    provider, _ = provider_for([first, done])
    meter = UsageMeter()
    reply = asyncio.run(provider.generate(HISTORY, "sys", meter=meter))
    assert (reply.input_tokens, reply.output_tokens, reply.cache_read_tokens, reply.requests) == (130, 24, 500, 2)
    assert (meter.input_tokens, meter.output_tokens, meter.cache_read_tokens, meter.requests) == (130, 24, 500, 2)


def test_streamed_turn_continues_and_tracks_a_step_across_requests():
    """The code run starts in the first request and its result arrives in the second."""
    provider, fake = provider_for([FIRST, DONE])
    meter = UsageMeter()
    items = asyncio.run(collect(provider.stream(HISTORY, "sys", tools=ALL_TOOLS, meter=meter)))

    steps = [i for i in items if isinstance(i, ToolStep)]
    assert [(s.id, s.status) for s in steps] == [("srvtoolu_1", "running"), ("srvtoolu_1", "ok")]
    assert [i for i in items if isinstance(i, str)] == ["Working on it.", "The answer is 2^100."]
    final = items[-1]
    assert isinstance(final, ModelResponse)
    assert (final.requests, [s.status for s in final.tool_steps]) == (2, ["ok"])
    assert (len(fake.requests), meter.requests) == (2, 2)


def test_later_continuations_send_all_paused_content_as_one_assistant_message():
    second_pause = paused({"type": "text", "text": "Still going."}, container="container_1")
    provider, fake = provider_for([FIRST, second_pause, DONE])
    asyncio.run(provider.generate(HISTORY, "sys", tools=ALL_TOOLS))
    third = fake.requests[2]["messages"]
    assert len(third) == len(HISTORY) + 1
    assert [b["type"] for b in third[-1]["content"]] == ["thinking", "text", "server_tool_use", "text"]


def test_continuations_are_capped():
    responses = [paused({"type": "text", "text": f"part {i}"}) for i in range(MAX_CONTINUATIONS + 3)]
    provider, fake = provider_for(responses)
    reply = asyncio.run(provider.generate(HISTORY, "sys"))
    assert len(fake.requests) == MAX_CONTINUATIONS + 1 == 4
    assert reply.stop_reason == "pause_turn"  # the UI can say the answer may be incomplete
    assert reply.requests == 4


@pytest.mark.parametrize("stop_reason", ["end_turn", "max_tokens", "tool_use", "stop_sequence"])
def test_only_pause_turn_continues(stop_reason: str):
    provider, fake = provider_for([make_message(stop_reason=stop_reason), make_message()])
    reply = asyncio.run(provider.generate(HISTORY, "sys"))
    assert len(fake.requests) == 1 and reply.stop_reason == stop_reason


def test_a_refusal_after_a_pause_still_raises():
    refusal = make_message(content=[{"type": "text", "text": "I can't"}], stop_reason="refusal",
                           stop_details={"type": "refusal", "category": "cyber", "explanation": None})
    provider, _ = provider_for([FIRST, refusal])
    with pytest.raises(ProviderRefusalError):
        asyncio.run(provider.generate(HISTORY, "sys", tools=ALL_TOOLS))


def test_no_container_means_none_is_sent():
    provider, fake = provider_for([paused({"type": "text", "text": "x"}, container=None), make_message()])
    asyncio.run(provider.generate(HISTORY, "sys"))
    assert "container" not in fake.requests[1]


def test_block_param_keeps_what_the_api_needs_and_drops_nulls():
    message = make_message([{"type": "text", "text": "hi"}, CODE_RESULT])
    text, result = (block_param(b) for b in message.content)
    assert text == {"type": "text", "text": "hi"}  # citations: None dropped
    assert result["content"]["stdout"].startswith("126765") and result["tool_use_id"] == "srvtoolu_1"
