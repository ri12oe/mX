"""AnthropicProvider.generate with the SDK mocked (no network, no cost)."""
import asyncio
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from api import main
from providers import create_provider
from providers.anthropic_provider import (
    DEFAULT_MAX_TOKENS,
    FALLBACK_BETA,
    AnthropicProvider,
    map_error,
)
from providers.base import Message
from providers.errors import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderUnavailableError,
)

MODEL = "claude-sonnet-5-5"
HISTORY = [
    Message(role="user", content="What is 2 + 2?"),
    Message(role="assistant", content="4."),
    Message(role="user", content="And times 3?"),
]
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def make_message(
    content: list[dict[str, Any]] | None = None,
    stop_reason: str = "end_turn",
    model: str = MODEL,
    **extra: Any,
) -> BetaMessage:
    return BetaMessage.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": model,
        "content": content if content is not None else [{"type": "text", "text": "12."}],
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 30, "output_tokens": 4},
        **extra,
    })


class FakeMessages:
    """Stands in for client.beta.messages: records kwargs, returns or raises."""

    def __init__(self, result: BetaMessage | Exception) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> BetaMessage:
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def provider_with(result: BetaMessage | Exception) -> tuple[AnthropicProvider, FakeMessages]:
    messages = FakeMessages(result)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return AnthropicProvider(api_key="unused", model=MODEL, client=client), messages


def status_error(status: int, message: str = "boom") -> anthropic.APIStatusError:
    return anthropic.APIStatusError(message, response=httpx2.Response(status, request=REQUEST), body=None)


# --- Setup -----------------------------------------------------------------


def test_real_client_uses_design_timeout_and_retries():
    provider = AnthropicProvider(api_key="sk-ant-test", model=MODEL)
    assert provider._client.timeout == 60.0
    assert provider._client.max_retries == 2


def test_create_provider_builds_anthropic_adapter():
    provider = create_provider("anthropic", api_key="sk-ant-test", model=MODEL)
    assert isinstance(provider, AnthropicProvider)
    assert (provider.name, provider.model) == ("anthropic", MODEL)


def test_get_provider_builds_the_configured_adapter():
    main.get_provider.cache_clear()
    try:
        assert isinstance(main.get_provider(), AnthropicProvider)
    finally:
        main.get_provider.cache_clear()


# --- Request shape ---------------------------------------------------------


def test_generate_sends_model_system_history_and_defaults():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, "You are mX."))

    assert fake.kwargs["model"] == MODEL
    assert fake.kwargs["system"] == "You are mX."
    assert fake.kwargs["max_tokens"] == DEFAULT_MAX_TOKENS
    assert fake.kwargs["messages"] == [
        {"role": "user", "content": "What is 2 + 2?"},
        {"role": "assistant", "content": "4."},
        {"role": "user", "content": "And times 3?"},
    ]


def test_generate_opts_into_refusal_fallbacks():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, "sys"))
    assert fake.kwargs["betas"] == [FALLBACK_BETA]
    assert fake.kwargs["fallbacks"] == "default"


def test_generate_passes_max_tokens():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, "sys", max_tokens=150))
    assert fake.kwargs["max_tokens"] == 150


def test_generate_rejects_unknown_options():
    provider, _ = provider_with(make_message())
    with pytest.raises(TypeError, match="max_token"):
        asyncio.run(provider.generate(HISTORY, "sys", max_token=150))


def test_images_are_rejected_until_week_3():
    provider, _ = provider_with(make_message())
    with pytest.raises(ProviderBadRequestError):
        asyncio.run(provider.generate([Message("user", "look", images=["aGk="])], "sys"))


# --- Response handling -----------------------------------------------------


def test_generate_returns_text_tokens_and_model():
    provider, _ = provider_with(make_message())
    reply = asyncio.run(provider.generate(HISTORY, "sys"))
    assert (reply.text, reply.model, reply.input_tokens, reply.output_tokens) == ("12.", MODEL, 30, 4)
    assert reply.stop_reason == "end_turn"


def test_thinking_blocks_are_dropped_and_text_blocks_joined():
    content = [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "Step 1. "},
        {"type": "text", "text": "Step 2."},
    ]
    provider, _ = provider_with(make_message(content))
    assert asyncio.run(provider.generate(HISTORY, "sys")).text == "Step 1. Step 2."


def test_truncated_reply_is_reported():
    provider, _ = provider_with(make_message(stop_reason="max_tokens"))
    assert asyncio.run(provider.generate(HISTORY, "sys")).stop_reason == "max_tokens"


def test_reports_the_model_that_actually_answered():
    """After a server-side fallback, response.model names the fallback model."""
    provider, _ = provider_with(make_message(model="claude-sonnet-5"))
    assert asyncio.run(provider.generate(HISTORY, "sys")).model == "claude-sonnet-5"


def test_refusal_raises_with_category():
    refusal = make_message(
        content=[], stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": None},
    )
    provider, _ = provider_with(refusal)
    with pytest.raises(ProviderRefusalError) as exc:
        asyncio.run(provider.generate(HISTORY, "sys"))
    assert exc.value.category == "cyber"


# --- Error mapping ---------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, ProviderBadRequestError),
        (401, ProviderAuthError),
        (402, ProviderRateLimitError),   # billing / spend limit
        (403, ProviderAuthError),
        (404, ProviderBadRequestError),  # unknown model id
        (408, ProviderUnavailableError),
        (413, ProviderBadRequestError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
        (529, ProviderUnavailableError),  # overloaded
    ],
)
def test_status_errors_map_to_provider_errors(status: int, expected: type[ProviderError]):
    assert type(map_error(status_error(status))) is expected


@pytest.mark.parametrize(
    "exc",
    [anthropic.APIConnectionError(request=REQUEST), anthropic.APITimeoutError(request=REQUEST)],
)
def test_network_errors_map_to_unavailable(exc: anthropic.APIError):
    assert isinstance(map_error(exc), ProviderUnavailableError)


def test_generate_raises_mapped_error_and_keeps_the_cause():
    sdk_error = anthropic.RateLimitError(
        "slow down", response=httpx2.Response(429, request=REQUEST), body=None
    )
    provider, _ = provider_with(sdk_error)
    with pytest.raises(ProviderRateLimitError) as exc:
        asyncio.run(provider.generate(HISTORY, "sys"))
    assert exc.value.__cause__ is sdk_error
    assert "429" in str(exc.value)
