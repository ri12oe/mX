"""Real-API smoke test (design.md §11). Costs about a cent.

Opt-in only:  pytest -m live
Skipped if ANTHROPIC_API_KEY isn't set.
"""
import asyncio

import pytest

from api.config import settings
from providers import create_provider
from providers.base import Message, ModelResponse, SystemPart, UsageMeter

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not settings.anthropic_api_key, reason="ANTHROPIC_API_KEY not set"),
]

SMOKE_SYSTEM = "You are a connectivity check. Reply with exactly the word: pong"


def test_real_stream_round_trip():
    provider = create_provider(
        settings.primary_provider,
        api_key=settings.anthropic_api_key,
        model=settings.primary_model,
    )

    async def run() -> list[str | ModelResponse]:
        stream = provider.stream(
            [Message(role="user", content="ping")], SMOKE_SYSTEM,
            max_tokens=1024, effort="low",
        )
        return [item async for item in stream]

    items = asyncio.run(run())
    chunks, final = items[:-1], items[-1]

    assert chunks and all(isinstance(c, str) for c in chunks)
    assert isinstance(final, ModelResponse)
    assert "pong" in final.text.lower()
    assert final.text == "".join(chunks)
    assert final.model.startswith("claude-")
    assert final.input_tokens > 0 and final.output_tokens > 0
    assert final.stop_reason == "end_turn"

    print(f"\nlive: model={final.model} in={final.input_tokens} out={final.output_tokens} text={final.text!r}")


# Deterministic filler so the cached prefix is well over Opus 5.5's 512-token minimum (~1,500 tokens).
CACHE_REFERENCE = "\n".join(
    f"Reference line {i}: the value of item {i} is {i * 7 % 101}, filed under group {i % 9}."
    for i in range(1, 121)
)


def test_real_prompt_cache_hit_on_second_identical_request():
    """Design §15: the same prefix sent twice is read from the cache the second time. About $0.01–0.02."""
    provider = create_provider(
        settings.primary_provider,
        api_key=settings.anthropic_api_key,
        model=settings.primary_model,
    )
    system = [SystemPart(SMOKE_SYSTEM + "\n\n" + CACHE_REFERENCE, cache=True)]
    messages = [Message(role="user", content="ping")]

    async def run(meter: UsageMeter) -> ModelResponse:
        items = [item async for item in provider.stream(
            messages, system, max_tokens=1024, effort="low", cache_messages=True, meter=meter,
        )]
        final = items[-1]
        assert isinstance(final, ModelResponse)
        return final

    first_meter, second_meter = UsageMeter(), UsageMeter()
    first = asyncio.run(run(first_meter))
    second = asyncio.run(run(second_meter))

    assert first.cache_write_5m_tokens + first.cache_read_tokens > 0  # written now, or still warm from a recent run
    assert second.cache_read_tokens > 0
    assert second.cache_read_tokens > second.input_tokens  # most of the prompt came from the cache
    assert (second_meter.cache_read_tokens, second_meter.output_tokens) == (second.cache_read_tokens, second.output_tokens)

    for label, r in (("first", first), ("second", second)):
        print(f"\nlive cache {label}: in={r.input_tokens} write5m={r.cache_write_5m_tokens} "
              f"read={r.cache_read_tokens} out={r.output_tokens}")
