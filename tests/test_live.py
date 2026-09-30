"""Real-API smoke test (design.md §11). Costs about a cent.

Opt-in only:  pytest -m live
Skipped if ANTHROPIC_API_KEY isn't set.
"""
import asyncio

import pytest

from api.config import settings
from providers import create_provider
from providers.base import Message, ModelResponse

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
