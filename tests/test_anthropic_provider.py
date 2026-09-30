"""AnthropicProvider.generate with the SDK mocked (no network, no cost)."""
import asyncio
import base64
from collections.abc import AsyncIterator
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
from providers.base import ImageData, Message, ModelResponse
from providers.errors import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderUnavailableError,
)

MODEL = "claude-opus-5-5"
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

    def __init__(self, result: BetaMessage | Exception, stream: "FakeStream | None" = None) -> None:
        self.result = result
        self.fake_stream = stream
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> BetaMessage:
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def stream(self, **kwargs: Any) -> "FakeStream":
        self.kwargs = kwargs
        assert self.fake_stream is not None
        return self.fake_stream


class FakeStream:
    """Stands in for the SDK's async stream manager + stream.

    Yields `chunks` from text_stream, optionally raising `error` when opened
    (`fail_after=None`) or after `fail_after` chunks.
    """

    def __init__(
        self,
        chunks: list[str],
        final: BetaMessage,
        error: Exception | None = None,
        fail_after: int | None = None,
    ) -> None:
        self.chunks, self.final, self.error, self.fail_after = chunks, final, error, fail_after
        self.closed = False
        self.text_stream = self._text()

    async def __aenter__(self) -> "FakeStream":
        if self.error is not None and self.fail_after is None:
            raise self.error
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        self.closed = True
        return False

    async def _text(self) -> AsyncIterator[str]:
        for i, chunk in enumerate(self.chunks):
            if self.error is not None and i == self.fail_after:
                raise self.error
            yield chunk

    async def get_final_message(self) -> BetaMessage:
        return self.final


def provider_with(
    result: BetaMessage | Exception, stream: FakeStream | None = None
) -> tuple[AnthropicProvider, FakeMessages]:
    messages = FakeMessages(result, stream)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return AnthropicProvider(api_key="unused", model=MODEL, client=client), messages


def streaming_provider(fake_stream: FakeStream) -> tuple[AnthropicProvider, FakeMessages]:
    return provider_with(make_message(), fake_stream)


async def collect(stream: AsyncIterator[str | ModelResponse]) -> list[str | ModelResponse]:
    return [item async for item in stream]


def status_error(status: int, message: str = "boom") -> anthropic.APIStatusError:
    return anthropic.APIStatusError(message, response=httpx2.Response(status, request=REQUEST), body=None)


# --- Setup -----------------------------------------------------------------


def test_real_client_uses_design_timeout_and_retries():
    provider = AnthropicProvider(api_key="sk-ant-test", model=MODEL)
    timeout = provider._client.timeout
    assert (timeout.connect, timeout.read) == (10.0, 600.0)  # fast connect, room for long replies
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


def test_generate_sends_effort_as_output_config():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, "sys", effort="high"))
    assert fake.kwargs["output_config"] == {"effort": "high"}


def test_generate_omits_effort_when_not_given():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, "sys"))
    assert "output_config" not in fake.kwargs


def test_generate_rejects_invalid_effort():
    provider, _ = provider_with(make_message())
    with pytest.raises(ValueError, match="effort"):
        asyncio.run(provider.generate(HISTORY, "sys", effort="extreme"))


def test_generate_rejects_unknown_options():
    provider, _ = provider_with(make_message())
    with pytest.raises(TypeError, match="max_token"):
        asyncio.run(provider.generate(HISTORY, "sys", max_token=150))


def test_images_are_sent_as_base64_blocks_before_the_text():
    provider, fake = provider_with(make_message())
    png = ImageData("image/png", b"\x89PNG\r\n\x1a\nfake")
    jpeg = ImageData("image/jpeg", b"\xff\xd8\xfffake")
    asyncio.run(provider.generate([Message("user", "Compare these", images=[png, jpeg])], "sys"))

    content = fake.kwargs["messages"][0]["content"]
    assert [block["type"] for block in content] == ["image", "image", "text"]
    assert content[0]["source"] == {
        "type": "base64", "media_type": "image/png",
        "data": base64.standard_b64encode(png.data).decode("ascii"),
    }
    assert content[1]["source"]["media_type"] == "image/jpeg"
    assert content[2] == {"type": "text", "text": "Compare these"}


def test_messages_without_images_stay_plain_text():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate([Message("user", "hi", images=None)], "sys"))
    assert fake.kwargs["messages"][0] == {"role": "user", "content": "hi"}


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
    provider, _ = provider_with(make_message(model="claude-opus-5"))
    assert asyncio.run(provider.generate(HISTORY, "sys")).model == "claude-opus-5"


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


# --- stream() --------------------------------------------------------------


def test_stream_yields_chunks_then_final_response():
    final = make_message([{"type": "text", "text": "Hello, Rio."}])
    provider, _ = streaming_provider(FakeStream(["Hello", ", ", "Rio."], final))
    items = asyncio.run(collect(provider.stream(HISTORY, "sys")))

    assert items[:-1] == ["Hello", ", ", "Rio."]
    last = items[-1]
    assert isinstance(last, ModelResponse)
    assert (last.text, last.model, last.input_tokens, last.output_tokens) == ("Hello, Rio.", MODEL, 30, 4)


def test_stream_sends_the_same_request_as_generate():
    provider, fake = streaming_provider(FakeStream(["ok"], make_message()))
    asyncio.run(collect(provider.stream(HISTORY, "You are mX.", max_tokens=2048, effort="low")))

    assert fake.kwargs["model"] == MODEL
    assert fake.kwargs["system"] == "You are mX."
    assert fake.kwargs["max_tokens"] == 2048
    assert fake.kwargs["output_config"] == {"effort": "low"}
    assert (fake.kwargs["betas"], fake.kwargs["fallbacks"]) == ([FALLBACK_BETA], "default")
    assert len(fake.kwargs["messages"]) == 3


def test_stream_error_before_any_text_is_mapped():
    provider, _ = streaming_provider(FakeStream(["never"], make_message(), error=status_error(529)))
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(collect(provider.stream(HISTORY, "sys")))


def test_stream_error_mid_reply_is_mapped_after_partial_text():
    fake_stream = FakeStream(
        ["a", "b", "c"], make_message(),
        error=anthropic.APIConnectionError(request=REQUEST), fail_after=2,
    )
    provider, _ = streaming_provider(fake_stream)
    received: list[str | ModelResponse] = []

    async def consume() -> None:
        async for item in provider.stream(HISTORY, "sys"):
            received.append(item)

    with pytest.raises(ProviderUnavailableError):
        asyncio.run(consume())
    assert received == ["a", "b"]  # partial text, no final response


def test_stream_unrescued_refusal_raises_after_partial_text():
    refusal = make_message(
        content=[{"type": "text", "text": "Sure, here"}], stop_reason="refusal",
        stop_details={"type": "refusal", "category": "bio", "explanation": None},
    )
    provider, _ = streaming_provider(FakeStream(["Sure, ", "here"], refusal))
    received: list[str | ModelResponse] = []

    async def consume() -> None:
        async for item in provider.stream(HISTORY, "sys"):
            received.append(item)

    with pytest.raises(ProviderRefusalError) as exc:
        asyncio.run(consume())
    assert received == ["Sure, ", "here"]  # caller must discard this partial
    assert exc.value.category == "bio"


def test_stream_mid_reply_fallback_continues_on_same_stream():
    """A rescued refusal: text from both models arrives; the final names the fallback."""
    final = make_message(
        [{"type": "text", "text": "Part one. "}, {"type": "text", "text": "Part two."}],
        model="claude-opus-5",
    )
    provider, _ = streaming_provider(FakeStream(["Part one. ", "Part two."], final))
    items = asyncio.run(collect(provider.stream(HISTORY, "sys")))
    last = items[-1]
    assert isinstance(last, ModelResponse)
    assert (last.text, last.model) == ("Part one. Part two.", "claude-opus-5")


def test_stream_closes_http_stream_when_caller_stops_early():
    """E.g. the browser disconnects: stop generating (and paying) right away."""
    fake_stream = FakeStream(["a", "b", "c"], make_message())
    provider, _ = streaming_provider(fake_stream)

    async def read_one_then_stop() -> None:
        gen = provider.stream(HISTORY, "sys")
        assert await gen.__anext__() == "a"
        await gen.aclose()

    asyncio.run(read_one_then_stop())
    assert fake_stream.closed


def test_stream_rejects_unknown_options():
    provider, _ = streaming_provider(FakeStream(["x"], make_message()))
    with pytest.raises(TypeError):
        asyncio.run(collect(provider.stream(HISTORY, "sys", temperature=0.2)))


def test_non_http_sdk_errors_map_to_the_base_error():
    error = map_error(anthropic.APIError("weird", request=REQUEST, body=None))
    assert type(error) is ProviderError
    assert "weird" in str(error)


def test_unexpected_status_maps_to_the_base_error():
    assert type(map_error(status_error(302))) is ProviderError
