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
from providers.base import ImageData, Message, ModelResponse, SystemPart, UsageMeter
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

    Iterating yields events like the SDK: `message_start`, a `text` event per
    chunk, then `message_delta`. `current_message_snapshot` holds the running
    usage: `start_usage` after message_start (default: the final usage with
    no output yet), the final usage after message_delta. Optionally raises
    `error` when opened (`fail_after=None`) or after `fail_after` chunks.
    """

    def __init__(
        self,
        chunks: list[str],
        final: BetaMessage,
        error: Exception | None = None,
        fail_after: int | None = None,
        start_usage: dict[str, Any] | None = None,
    ) -> None:
        self.chunks, self.final, self.error, self.fail_after = chunks, final, error, fail_after
        default_start = {**final.usage.model_dump(exclude_none=True), "output_tokens": 0}
        self.start = BetaMessage.model_validate({**final.model_dump(), "usage": start_usage or default_start})
        self.current_message_snapshot: BetaMessage | None = None
        self.closed = False

    async def __aenter__(self) -> "FakeStream":
        if self.error is not None and self.fail_after is None:
            raise self.error
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        self.closed = True
        return False

    async def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        self.current_message_snapshot = self.start
        yield SimpleNamespace(type="message_start")
        for i, chunk in enumerate(self.chunks):
            if self.error is not None and i == self.fail_after:
                raise self.error
            yield SimpleNamespace(type="text", text=chunk)
        self.current_message_snapshot = self.final
        yield SimpleNamespace(type="message_delta")

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


# --- Prompt caching (design.md §15) ----------------------------------------

PARTS = [SystemPart("Core prompt.", cache=True), SystemPart("Learner profile.", cache=True), SystemPart("Tail.")]
CACHED_USAGE = {
    "input_tokens": 20, "output_tokens": 7, "cache_read_input_tokens": 3000,
    "cache_creation_input_tokens": 600,
    "cache_creation": {"ephemeral_5m_input_tokens": 500, "ephemeral_1h_input_tokens": 100},
    "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 0},
}


def test_plain_string_system_has_no_cache_markers():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, "You are mX."))
    assert fake.kwargs["system"] == "You are mX."
    assert "cache_control" not in fake.kwargs


def test_marked_system_parts_get_breakpoints_in_order():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, PARTS))
    assert fake.kwargs["system"] == [
        {"type": "text", "text": "Core prompt.", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
        {"type": "text", "text": "Learner profile.", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
        {"type": "text", "text": "Tail."},
    ]
    assert "cache_control" not in fake.kwargs  # messages not cached unless asked


def test_cache_messages_adds_top_level_automatic_caching():
    provider, fake = streaming_provider(FakeStream(["ok"], make_message()))
    asyncio.run(collect(provider.stream(HISTORY, PARTS, cache_messages=True)))
    assert fake.kwargs["cache_control"] == {"type": "ephemeral", "ttl": "5m"}


def test_one_hour_ttl_is_used_by_every_breakpoint():
    """Longer TTLs must come first; using one TTL everywhere keeps that true (§15)."""
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, PARTS, cache_messages=True, cache_ttl="1h"))
    markers = [b["cache_control"] for b in fake.kwargs["system"] if "cache_control" in b]
    markers.append(fake.kwargs["cache_control"])
    assert markers == [{"type": "ephemeral", "ttl": "1h"}] * 3


def test_rejects_unknown_ttl():
    provider, _ = provider_with(make_message())
    with pytest.raises(ValueError, match="cache_ttl"):
        asyncio.run(provider.generate(HISTORY, PARTS, cache_ttl="1d"))


def test_at_most_four_breakpoints():
    four = [SystemPart(str(i), cache=True) for i in range(4)]
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, four))  # 4 explicit: allowed
    assert len(fake.kwargs["system"]) == 4
    with pytest.raises(ValueError, match="breakpoints"):
        asyncio.run(provider.generate(HISTORY, four, cache_messages=True))  # 4 + automatic = 5


def test_response_reports_cache_and_tool_usage():
    provider, _ = provider_with(make_message(usage=CACHED_USAGE))
    reply = asyncio.run(provider.generate(HISTORY, PARTS))
    assert (reply.input_tokens, reply.output_tokens) == (20, 7)
    assert (reply.cache_read_tokens, reply.cache_write_5m_tokens, reply.cache_write_1h_tokens) == (3000, 500, 100)
    assert (reply.web_searches, reply.code_runs, reply.requests) == (2, 0, 1)


@pytest.mark.parametrize(("ttl", "expected"), [("5m", (400, 0)), ("1h", (0, 400))])
def test_cache_writes_without_a_split_go_to_the_requests_ttl(ttl: str, expected: tuple[int, int]):
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_creation_input_tokens": 400}
    provider, _ = provider_with(make_message(usage=usage))
    reply = asyncio.run(provider.generate(HISTORY, PARTS, cache_ttl=ttl))
    assert (reply.cache_write_5m_tokens, reply.cache_write_1h_tokens) == expected


def test_reply_without_cache_fields_counts_zero():
    reply = asyncio.run(provider_with(make_message())[0].generate(HISTORY, "sys"))
    assert (reply.cache_read_tokens, reply.cache_write_5m_tokens, reply.web_searches) == (0, 0, 0)


# --- Usage meter -----------------------------------------------------------


def test_stream_fills_the_meter():
    final = make_message(usage=CACHED_USAGE)
    provider, _ = streaming_provider(FakeStream(["Hi"], final))
    meter = UsageMeter()
    asyncio.run(collect(provider.stream(HISTORY, PARTS, meter=meter)))
    assert meter == UsageMeter(
        input_tokens=20, output_tokens=7, cache_read_tokens=3000, cache_write_5m_tokens=500,
        cache_write_1h_tokens=100, web_searches=2, code_runs=0, requests=1, model=MODEL,
    )


def test_meter_is_filled_before_a_mid_stream_error():
    """The input side is known at message_start, so a failed turn's spend is still recorded."""
    start = {"input_tokens": 20, "output_tokens": 0, "cache_read_input_tokens": 3000,
             "cache_creation_input_tokens": 600,
             "cache_creation": {"ephemeral_5m_input_tokens": 600, "ephemeral_1h_input_tokens": 0}}
    fake_stream = FakeStream(["a", "b"], make_message(usage=CACHED_USAGE), start_usage=start,
                             error=anthropic.APIConnectionError(request=REQUEST), fail_after=1)
    provider, _ = streaming_provider(fake_stream)
    meter = UsageMeter()
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(collect(provider.stream(HISTORY, PARTS, meter=meter)))
    assert (meter.requests, meter.input_tokens, meter.cache_read_tokens, meter.cache_write_5m_tokens) == (1, 20, 3000, 600)
    assert meter.output_tokens == 0


def test_meter_adds_to_what_the_turn_already_spent():
    """A later request in the same turn (tool loop, week 2) adds to the totals."""
    provider, _ = streaming_provider(FakeStream(["ok"], make_message()))  # 30 in, 4 out
    meter = UsageMeter(input_tokens=100, output_tokens=50, requests=1)
    asyncio.run(collect(provider.stream(HISTORY, "sys", meter=meter)))
    assert (meter.input_tokens, meter.output_tokens, meter.requests) == (130, 54, 2)


def test_generate_fills_the_meter():
    provider, _ = provider_with(make_message(usage=CACHED_USAGE))
    meter = UsageMeter()
    asyncio.run(provider.generate(HISTORY, PARTS, meter=meter))
    assert (meter.requests, meter.cache_read_tokens, meter.model) == (1, 3000, MODEL)


def test_failed_generate_leaves_the_meter_empty():
    provider, _ = provider_with(status_error(529))
    meter = UsageMeter()
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(provider.generate(HISTORY, "sys", meter=meter))
    assert meter == UsageMeter()


def test_non_http_sdk_errors_map_to_the_base_error():
    error = map_error(anthropic.APIError("weird", request=REQUEST, body=None))
    assert type(error) is ProviderError
    assert "weird" in str(error)


def test_unexpected_status_maps_to_the_base_error():
    assert type(map_error(status_error(302))) is ProviderError
