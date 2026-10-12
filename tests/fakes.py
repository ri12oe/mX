"""Test doubles (design.md §11). No network, no cost."""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from typing import Any

from providers.base import Citation, Message, ModelResponse, SystemPrompt, ToolStep, UsageMeter
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
    script: list[str | ToolStep] | None = None  # text and tool steps to yield instead of `chunks`
    citations: list[Citation] = field(default_factory=list)
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
    ) -> AsyncIterator[str | ToolStep | ModelResponse]:
        self.calls.append(Call("stream", messages, system, opts))
        meter: UsageMeter | None = opts.get("meter")
        if self.error is not None and self.fail_after is None:
            raise self.error
        self._meter_start(meter)
        for i, item in enumerate(self._items()):
            if self.error is not None and i == self.fail_after:
                raise self.error
            yield replace(item) if isinstance(item, ToolStep) else item
        self._meter_end(meter)
        yield self._response()

    def _items(self) -> list[str | ToolStep]:
        return list(self.script) if self.script is not None else list(self.chunks)

    def _final_steps(self) -> list[ToolStep]:
        """The last state of each step, in the order the steps started."""
        final: dict[str, ToolStep] = {}
        for item in self._items():
            if isinstance(item, ToolStep):
                final[item.id] = replace(item)
        return list(final.values())

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
        steps = self._final_steps()
        return ModelResponse(
            text="".join(item for item in self._items() if isinstance(item, str)),
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_5m_tokens=self.cache_write_5m_tokens,
            web_searches=sum(s.tool == "web_search" and s.status != "error" for s in steps),
            code_runs=sum(s.tool == "code_execution" for s in steps),
            tool_steps=steps,
            citations=list(self.citations),
        )
