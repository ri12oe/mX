"""Test doubles (design.md §11). No network, no cost."""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from providers.base import Message, ModelResponse
from providers.errors import ProviderError


@dataclass
class Call:
    """What a route passed to the provider, for assertions."""

    method: str
    messages: list[Message]
    system: str
    opts: dict[str, Any]


@dataclass
class FakeProvider:
    """Scripted stand-in for a real provider.

    - `chunks`: text pieces `stream` yields, joined for `generate`.
    - `error`: raised instead of replying. With `fail_after=None` it's raised
      before any text; with `fail_after=n` it's raised after `n` chunks
      (simulates a failure mid-stream).
    - `calls`: every call made, so tests can check history, system prompt, opts.
    """

    chunks: list[str] = field(default_factory=lambda: ["Hello", ", ", "Rio."])
    model: str = "fake-model"
    input_tokens: int = 12
    output_tokens: int = 3
    error: ProviderError | None = None
    fail_after: int | None = None
    name: str = "fake"
    calls: list[Call] = field(default_factory=list)

    async def generate(
        self, messages: list[Message], system: str, **opts: Any
    ) -> ModelResponse:
        self.calls.append(Call("generate", messages, system, opts))
        if self.error is not None:
            raise self.error
        return self._response()

    async def stream(
        self, messages: list[Message], system: str, **opts: Any
    ) -> AsyncIterator[str | ModelResponse]:
        self.calls.append(Call("stream", messages, system, opts))
        if self.error is not None and self.fail_after is None:
            raise self.error
        for i, chunk in enumerate(self.chunks):
            if self.error is not None and i == self.fail_after:
                raise self.error
            yield chunk
        yield self._response()

    def _response(self) -> ModelResponse:
        return ModelResponse(
            text="".join(self.chunks),
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )
