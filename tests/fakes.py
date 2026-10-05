"""Test doubles (design.md §11). No network, no cost."""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from providers.base import Message, ModelResponse, SystemPrompt, UsageMeter
from providers.errors import ProviderError


@dataclass
class Call:
    """What a route passed to the provider, for assertions."""

    method: str
    messages: list[Message]
    system: SystemPrompt
    opts: dict[str, Any]


@dataclass
class FakeProvider:
    """Scripted stand-in for a real provider.

    - `chunks`: text pieces `stream` yields, joined for `generate`.
    - `error`: raised instead of replying. With `fail_after=None` it's raised
      before any text; with `fail_after=n` it's raised after `n` chunks
      (simulates a failure mid-stream).
    - `calls`: every call made, so tests can check history, system prompt, opts.
    - A `meter=` option is filled like the real adapter: input side when the
      stream starts, output when it ends (so a mid-stream failure leaves the
      input side recorded).
    """

    chunks: list[str] = field(default_factory=lambda: ["Hello", ", ", "Rio."])
    model: str = "fake-model"
    input_tokens: int = 12
    output_tokens: int = 3
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    error: ProviderError | None = None
    fail_after: int | None = None
    name: str = "fake"
    calls: list[Call] = field(default_factory=list)

    async def generate(
        self, messages: list[Message], system: SystemPrompt, **opts: Any
    ) -> ModelResponse:
        self.calls.append(Call("generate", messages, system, opts))
        if self.error is not None:
            raise self.error
        self._meter_start(opts.get("meter"))
        self._meter_end(opts.get("meter"))
        return self._response()

    async def stream(
        self, messages: list[Message], system: SystemPrompt, **opts: Any
    ) -> AsyncIterator[str | ModelResponse]:
        self.calls.append(Call("stream", messages, system, opts))
        meter: UsageMeter | None = opts.get("meter")
        if self.error is not None and self.fail_after is None:
            raise self.error
        self._meter_start(meter)
        for i, chunk in enumerate(self.chunks):
            if self.error is not None and i == self.fail_after:
                raise self.error
            yield chunk
        self._meter_end(meter)
        yield self._response()

    def _meter_start(self, meter: UsageMeter | None) -> None:
        if meter is not None:
            meter.requests += 1
            meter.model = self.model
            meter.input_tokens += self.input_tokens
            meter.cache_read_tokens += self.cache_read_tokens
            meter.cache_write_5m_tokens += self.cache_write_5m_tokens

    def _meter_end(self, meter: UsageMeter | None) -> None:
        if meter is not None:
            meter.output_tokens += self.output_tokens

    def _response(self) -> ModelResponse:
        return ModelResponse(
            text="".join(self.chunks),
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_5m_tokens=self.cache_write_5m_tokens,
        )
