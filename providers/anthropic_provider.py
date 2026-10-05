"""Anthropic adapter (design.md §6). The only module that imports the anthropic SDK."""
import base64
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam

from providers.base import Message, ModelResponse, SystemPrompt, UsageMeter
from providers.errors import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderUnavailableError,
)

# Connecting should be quick; a long, carefully reasoned reply can take minutes.
# A short read timeout would cut those off and the SDK would retry (and bill) them.
DEFAULT_TIMEOUT = anthropic.Timeout(600.0, connect=10.0)
DEFAULT_MAX_RETRIES = 2  # SDK retries connection errors, 408, 409, 429, and 5xx
DEFAULT_MAX_TOKENS = 16000  # a ceiling, not a cost: only tokens actually used are billed
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
CACHE_TTLS = ("5m", "1h")
MAX_CACHE_BREAKPOINTS = 4  # API limit per request (design.md §15)

# If the model's safety classifiers decline a request, let Anthropic retry it on
# its recommended fallback model instead of returning the refusal.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    """ModelProvider backed by the Claude API."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float | anthropic.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        client: Any = None,
    ) -> None:
        """`client` is only for tests; normally a real AsyncAnthropic is built."""
        self.model = model
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key or None, timeout=timeout, max_retries=max_retries
        )

    async def generate(
        self,
        messages: list[Message],
        system: SystemPrompt,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str | None = None,
        cache_messages: bool = False,
        cache_ttl: str = "5m",
        meter: UsageMeter | None = None,
        **opts: Any,
    ) -> ModelResponse:
        """Send the conversation and return the whole reply.

        `effort` controls how hard the model thinks (and how many tokens it
        spends). None uses the model's default. Caching options: see stream().
        """
        params = self._params(messages, system, max_tokens, effort, cache_messages, cache_ttl, opts)
        metering = _Metering(meter, cache_ttl)
        try:
            response = await self._client.beta.messages.create(**params)
        except anthropic.APIError as exc:
            raise map_error(exc) from exc
        metering.request_started()
        metering.update(response)
        return to_model_response(response, cache_ttl)

    async def stream(
        self,
        messages: list[Message],
        system: SystemPrompt,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str | None = None,
        cache_messages: bool = False,
        cache_ttl: str = "5m",
        meter: UsageMeter | None = None,
        **opts: Any,
    ) -> AsyncIterator[str | ModelResponse]:
        """Yield text chunks as they arrive, then one final ModelResponse.

        Caching (design.md §15): system parts marked `cache=True` get a cache
        breakpoint; `cache_messages=True` adds automatic caching of the whole
        conversation (top-level `cache_control`). All breakpoints use `cache_ttl`.
        `meter`, if given, is kept up to date at `message_start` and
        `message_delta`, so it holds what was spent even if the stream fails.

        If a refusal is rescued mid-stream, the fallback model continues on the
        same stream. An unrescued refusal raises ProviderRefusalError after the
        partial text; callers must discard it. If the caller stops iterating
        (e.g. the browser disconnects), the HTTP stream is closed.
        """
        params = self._params(messages, system, max_tokens, effort, cache_messages, cache_ttl, opts)
        metering = _Metering(meter, cache_ttl)
        try:
            async with self._client.beta.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield event.text
                    elif event.type in ("message_start", "message_delta"):
                        if event.type == "message_start":
                            metering.request_started()
                        metering.update(stream.current_message_snapshot)
                final = await stream.get_final_message()
        except anthropic.APIError as exc:
            raise map_error(exc) from exc
        yield to_model_response(final, cache_ttl)

    def _params(
        self,
        messages: list[Message],
        system: SystemPrompt,
        max_tokens: int,
        effort: str | None,
        cache_messages: bool,
        cache_ttl: str,
        opts: dict[str, Any],
    ) -> dict[str, Any]:
        """Request body shared by generate() and stream()."""
        _reject_unknown_opts(opts)
        cache_control = _cache_control(cache_ttl)
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": to_system_param(system, cache_control, reserved=int(cache_messages)),
            "messages": [to_message_param(m) for m in messages],
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        if cache_messages:
            params["cache_control"] = cache_control  # automatic: marks the last cacheable block
        if effort is not None:
            params["output_config"] = {"effort": _checked_effort(effort)}
        return params


# --- Usage metering --------------------------------------------------------


class _Metering:
    """Keeps a caller's UsageMeter equal to (usage before this request) + (this request so far).

    The SDK's message snapshot already folds `message_delta` usage in
    (those counts are cumulative), so each update just re-reads it.
    """

    def __init__(self, meter: UsageMeter | None, cache_ttl: str) -> None:
        self.meter, self.cache_ttl = meter, cache_ttl
        self.base: UsageMeter | None = None

    def request_started(self) -> None:
        if self.meter is not None:
            self.meter.requests += 1
            self.base = replace(self.meter)

    def update(self, message: Any) -> None:
        if self.meter is None or self.base is None:
            return
        counts = usage_counts(message.usage, self.cache_ttl)
        for name, value in counts.items():
            setattr(self.meter, name, getattr(self.base, name) + value)
        self.meter.model = message.model


# --- Conversions -----------------------------------------------------------


def to_message_param(message: Message) -> BetaMessageParam:
    """Plain text, or image blocks followed by the text (images first works best)."""
    if not message.images:
        return {"role": message.role, "content": message.content}  # type: ignore[typeddict-item]
    blocks: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image.media_type,
                "data": base64.standard_b64encode(image.data).decode("ascii"),
            },
        }
        for image in message.images
    ]
    blocks.append({"type": "text", "text": message.content})
    return {"role": message.role, "content": blocks}  # type: ignore[typeddict-item]


def to_system_param(
    system: SystemPrompt, cache_control: dict[str, str], reserved: int = 0
) -> str | list[dict[str, Any]]:
    """A plain string stays a string; parts become text blocks, with breakpoints where marked.

    `reserved` breakpoints are kept free for automatic message caching; the
    API allows 4 in total.
    """
    if isinstance(system, str):
        return system
    marked = sum(part.cache for part in system)
    if marked + reserved > MAX_CACHE_BREAKPOINTS:
        raise ValueError(
            f"{marked + reserved} cache breakpoints requested; the API allows {MAX_CACHE_BREAKPOINTS}."
        )
    blocks: list[dict[str, Any]] = []
    for part in system:
        block: dict[str, Any] = {"type": "text", "text": part.text}
        if part.cache:
            block["cache_control"] = dict(cache_control)
        blocks.append(block)
    return blocks


def usage_counts(usage: Any, cache_ttl: str) -> dict[str, int]:
    """Token and tool counts from an SDK usage object, in UsageMeter/ModelResponse field names.

    The 5m/1h split of cache writes is only reported at message_start
    (`cache_creation`); any later increase in the total is put in the
    request's own TTL bucket.
    """
    split = getattr(usage, "cache_creation", None)
    write_5m = getattr(split, "ephemeral_5m_input_tokens", 0) or 0
    write_1h = getattr(split, "ephemeral_1h_input_tokens", 0) or 0
    unsplit = max(0, (usage.cache_creation_input_tokens or 0) - write_5m - write_1h)
    if cache_ttl == "1h":
        write_1h += unsplit
    else:
        write_5m += unsplit
    tools = getattr(usage, "server_tool_use", None)
    return {
        "input_tokens": usage.input_tokens or 0,
        "output_tokens": usage.output_tokens or 0,
        "cache_read_tokens": usage.cache_read_input_tokens or 0,
        "cache_write_5m_tokens": write_5m,
        "cache_write_1h_tokens": write_1h,
        "web_searches": getattr(tools, "web_search_requests", 0) or 0,
        "code_runs": getattr(tools, "code_execution_requests", 0) or 0,
    }


def to_model_response(response: BetaMessage, cache_ttl: str = "5m") -> ModelResponse:
    """Keep only the visible text; thinking blocks are internal to the model."""
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ProviderRefusalError("The model declined this request.", category=category)
    text = "".join(block.text for block in response.content if block.type == "text")
    return ModelResponse(
        text=text,
        model=response.model,
        stop_reason=response.stop_reason or "end_turn",
        **usage_counts(response.usage, cache_ttl),
    )


def map_error(exc: anthropic.APIError) -> ProviderError:
    """Translate an SDK exception into a provider-neutral error (design.md §6).

    Mapped by HTTP status so codes without their own SDK class (402 billing,
    529 overloaded) are still handled.
    """
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return ProviderUnavailableError("Couldn't reach Anthropic (network error or timeout).")
    if not isinstance(exc, anthropic.APIStatusError):
        return ProviderError(f"Unexpected Anthropic error: {exc.message}")

    status = exc.status_code
    detail = f"Anthropic returned {status}: {exc.message}"
    if status in (401, 403):
        return ProviderAuthError(detail)
    if status in (402, 429):  # billing / spend limit, or rate limited
        return ProviderRateLimitError(detail)
    if status >= 500 or status in (408, 409):
        return ProviderUnavailableError(detail)
    if 400 <= status < 500:  # 400, 404 (unknown model), 413, 422
        return ProviderBadRequestError(detail)
    return ProviderError(detail)


def _cache_control(ttl: str) -> dict[str, str]:
    if ttl not in CACHE_TTLS:
        raise ValueError(f"cache_ttl must be one of {', '.join(CACHE_TTLS)}, got {ttl!r}")
    return {"type": "ephemeral", "ttl": ttl}


def _checked_effort(effort: str) -> str:
    if effort not in EFFORT_LEVELS:
        raise ValueError(f"effort must be one of {', '.join(EFFORT_LEVELS)}, got {effort!r}")
    return effort


def _reject_unknown_opts(opts: dict[str, Any]) -> None:
    """Fail loudly on typos like `max_token=` instead of silently ignoring them."""
    if opts:
        raise TypeError(f"Unsupported option(s): {', '.join(sorted(opts))}")
