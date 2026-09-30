import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api import main
from providers import ModelProvider, create_provider
from providers.base import Message, ModelResponse
from providers.errors import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    UnknownProviderError,
)
from tests.fakes import FakeProvider

ERROR_TYPES = [
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    ProviderBadRequestError,
    UnknownProviderError,
]
HISTORY = [Message(role="user", content="Hi")]


async def collect(stream: AsyncIterator[str | ModelResponse]) -> list[str | ModelResponse]:
    return [item async for item in stream]


# --- Errors ----------------------------------------------------------------


@pytest.mark.parametrize("error_type", ERROR_TYPES)
def test_errors_share_base_class(error_type: type[ProviderError]):
    assert issubclass(error_type, ProviderError)


def test_error_codes_are_unique():
    codes = [ProviderError.code] + [e.code for e in ERROR_TYPES]
    assert len(codes) == len(set(codes))


# --- FakeProvider follows the stream contract ------------------------------


def test_fake_satisfies_the_protocol():
    assert isinstance(FakeProvider(), ModelProvider)


def test_stream_yields_chunks_then_one_final_response():
    fake = FakeProvider(chunks=["a", "b", "c"], input_tokens=7, output_tokens=2)
    items = asyncio.run(collect(fake.stream(HISTORY, "sys")))

    assert items[:-1] == ["a", "b", "c"]
    final = items[-1]
    assert isinstance(final, ModelResponse)
    assert (final.text, final.input_tokens, final.output_tokens) == ("abc", 7, 2)


def test_generate_returns_full_reply():
    reply = asyncio.run(FakeProvider(chunks=["x", "y"]).generate(HISTORY, "sys"))
    assert reply.text == "xy"


def test_fake_records_calls():
    fake = FakeProvider()
    asyncio.run(collect(fake.stream(HISTORY, "be formal", max_tokens=150)))
    call = fake.calls[0]
    assert (call.method, call.system, call.opts) == ("stream", "be formal", {"max_tokens": 150})
    assert call.messages == HISTORY


def test_fake_can_fail_before_any_text():
    fake = FakeProvider(error=ProviderUnavailableError("down"))
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(collect(fake.stream(HISTORY, "sys")))
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(fake.generate(HISTORY, "sys"))


def test_fake_can_fail_mid_stream():
    fake = FakeProvider(chunks=["a", "b", "c"], error=ProviderRateLimitError("slow down"), fail_after=2)
    received: list[str | ModelResponse] = []

    async def consume() -> None:
        async for item in fake.stream(HISTORY, "sys"):
            received.append(item)

    with pytest.raises(ProviderRateLimitError):
        asyncio.run(consume())
    assert received == ["a", "b"]  # two chunks arrived, no final response


# --- Building and injecting the provider -----------------------------------


def test_unknown_provider_name_is_rejected():
    with pytest.raises(UnknownProviderError):
        create_provider("does-not-exist", api_key="k", model="m")


def test_get_provider_uses_configured_name(monkeypatch: pytest.MonkeyPatch):
    main.get_provider.cache_clear()
    monkeypatch.setattr(main.settings, "primary_provider", "does-not-exist")
    try:
        with pytest.raises(UnknownProviderError):
            main.get_provider()
    finally:
        main.get_provider.cache_clear()


def test_routes_can_swap_in_the_fake_provider():
    """The pattern /chat tests will use (task 8)."""
    demo = FastAPI()

    @demo.get("/provider-name")
    def provider_name(provider: ModelProvider = Depends(main.get_provider)) -> dict[str, str]:
        return {"name": provider.name}

    demo.dependency_overrides[main.get_provider] = lambda: FakeProvider()
    assert TestClient(demo).get("/provider-name").json() == {"name": "fake"}
