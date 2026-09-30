"""Anthropic adapter (design.md §6). The only module that imports the anthropic SDK."""
import base64
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam

from providers.base import Message, ModelResponse
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
        system: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str | None = None,
        **opts: Any,
    ) -> ModelResponse:
        """Send the conversation and return the whole reply.

        `effort` controls how hard the model thinks (and how many tokens it
        spends). None uses the model's default.
        """
        params = self._params(messages, system, max_tokens, effort, opts)
        try:
            response = await self._client.beta.messages.create(**params)
        except anthropic.APIError as exc:
            raise map_error(exc) from exc
        return to_model_response(response)

    async def stream(
        self,
        messages: list[Message],
        system: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str | None = None,
        **opts: Any,
    ) -> AsyncIterator[str | ModelResponse]:
        """Yield text chunks as they arrive, then one final ModelResponse.

        If a refusal is rescued mid-stream, the fallback model continues on the
        same stream. An unrescued refusal raises ProviderRefusalError after the
        partial text; callers must discard it. If the caller stops iterating
        (e.g. the browser disconnects), the HTTP stream is closed.
        """
        params = self._params(messages, system, max_tokens, effort, opts)
        try:
            async with self._client.beta.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except anthropic.APIError as exc:
            raise map_error(exc) from exc
        yield to_model_response(final)

    def _params(
        self,
        messages: list[Message],
        system: str,
        max_tokens: int,
        effort: str | None,
        opts: dict[str, Any],
    ) -> dict[str, Any]:
        """Request body shared by generate() and stream()."""
        _reject_unknown_opts(opts)
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [to_message_param(m) for m in messages],
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        if effort is not None:
            params["output_config"] = {"effort": _checked_effort(effort)}
        return params


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


def to_model_response(response: BetaMessage) -> ModelResponse:
    """Keep only the visible text; thinking blocks are internal to the model."""
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ProviderRefusalError("The model declined this request.", category=category)
    text = "".join(block.text for block in response.content if block.type == "text")
    return ModelResponse(
        text=text,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        stop_reason=response.stop_reason or "end_turn",
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


def _checked_effort(effort: str) -> str:
    if effort not in EFFORT_LEVELS:
        raise ValueError(f"effort must be one of {', '.join(EFFORT_LEVELS)}, got {effort!r}")
    return effort


def _reject_unknown_opts(opts: dict[str, Any]) -> None:
    """Fail loudly on typos like `max_token=` instead of silently ignoring them."""
    if opts:
        raise TypeError(f"Unsupported option(s): {', '.join(sorted(opts))}")
