"""Anthropic adapter (design.md §6). The only module that imports the anthropic SDK."""
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

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_RETRIES = 2  # SDK retries connection errors, 408, 409, 429, and 5xx
DEFAULT_MAX_TOKENS = 4096

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
        timeout: float = DEFAULT_TIMEOUT_S,
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
        **opts: Any,
    ) -> ModelResponse:
        """Send the conversation and return the whole reply."""
        _reject_unknown_opts(opts)
        try:
            response = await self._client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[to_message_param(m) for m in messages],
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIError as exc:
            raise map_error(exc) from exc
        return to_model_response(response)

    def stream(
        self, messages: list[Message], system: str, **opts: Any
    ) -> AsyncIterator[str | ModelResponse]:
        raise NotImplementedError("Streaming arrives in Week 2, task 6.")


# --- Conversions -----------------------------------------------------------


def to_message_param(message: Message) -> BetaMessageParam:
    if message.images:
        raise ProviderBadRequestError("Image input isn't supported yet (Week 3).")
    return {"role": message.role, "content": message.content}  # type: ignore[typeddict-item]


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


def _reject_unknown_opts(opts: dict[str, Any]) -> None:
    """Fail loudly on typos like `max_token=` instead of silently ignoring them."""
    if opts:
        raise TypeError(f"Unsupported option(s): {', '.join(sorted(opts))}")
