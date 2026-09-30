"""Provider interface (design.md §6). Every model provider implements this.

The API layer only talks to `ModelProvider`; SDKs are used only inside
provider adapters such as providers/anthropic_provider.py.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ImageData:
    media_type: str  # "image/jpeg" | "image/png" | "image/gif" | "image/webp"
    data: bytes


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str
    images: list[ImageData] | None = None  # only on the current turn's user message


@dataclass
class ModelResponse:
    text: str
    model: str  # the model that actually answered (may differ after a fallback)
    input_tokens: int
    output_tokens: int
    stop_reason: str = "end_turn"  # "max_tokens" means the reply was cut off


@runtime_checkable
class ModelProvider(Protocol):
    name: str

    async def generate(
        self, messages: list[Message], system: str, **opts: Any
    ) -> ModelResponse:
        """Return the whole reply at once."""
        ...

    def stream(
        self, messages: list[Message], system: str, **opts: Any
    ) -> AsyncIterator[str | ModelResponse]:
        """Yield the reply as `str` chunks, then exactly one final `ModelResponse`.

        The final item carries the full text and token counts, so cost can be
        logged for streamed replies too. Nothing is yielded after it.
        Raises a `ProviderError` subclass on failure.
        """
        ...
