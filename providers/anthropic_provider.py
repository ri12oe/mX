"""Anthropic adapter (design.md §6). The only module that imports the anthropic SDK."""
import base64
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam

from providers.base import Citation, Message, ModelResponse, SystemPrompt, ToolOptions, ToolStep, UsageMeter
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

# Server tools (design.md §17), declared in this fixed order so the cached prefix never changes.
# Versions checked 2026-10-12 against the Claude API reference and SDK 1.9.0 types.
CODE_EXECUTION_TOOL = {"type": "code_execution_20260120", "name": "code_execution"}
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"  # dynamic filtering on Opus 5.5
CODE_TOOL_NAMES = {"code_execution", "bash_code_execution", "text_editor_code_execution"}
CODE_RESULT_TYPES = {"code_execution_tool_result", "bash_code_execution_tool_result",
                     "text_editor_code_execution_tool_result"}


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
        tools: ToolOptions | None = None,
        **opts: Any,
    ) -> ModelResponse:
        """Send the conversation and return the whole reply.

        `effort` controls how hard the model thinks (and how many tokens it
        spends). None uses the model's default. Caching options: see stream().
        """
        params = self._params(messages, system, max_tokens, effort, cache_messages, cache_ttl, tools, opts)
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
        tools: ToolOptions | None = None,
        **opts: Any,
    ) -> AsyncIterator[str | ToolStep | ModelResponse]:
        """Yield text chunks as they arrive, then one final ModelResponse.

        Caching (design.md §15): system parts marked `cache=True` get a cache
        breakpoint; `cache_messages=True` adds automatic caching of the whole
        conversation (top-level `cache_control`). All breakpoints use `cache_ttl`.
        `meter`, if given, is kept up to date at `message_start` and
        `message_delta`, so it holds what was spent even if the stream fails.

        Tools (design.md §17): `tools` declares code execution and/or web
        search; with `enabled=False` they stay declared (so the cache holds)
        but `tool_choice: none` keeps the model from calling them. Each server
        tool step is yielded as a `ToolStep` when its input is complete
        ("running") and again when its result arrives ("ok"/"error").

        If a refusal is rescued mid-stream, the fallback model continues on the
        same stream. An unrescued refusal raises ProviderRefusalError after the
        partial text; callers must discard it. If the caller stops iterating
        (e.g. the browser disconnects), the HTTP stream is closed.
        """
        params = self._params(messages, system, max_tokens, effort, cache_messages, cache_ttl, tools, opts)
        metering = _Metering(meter, cache_ttl)
        steps = ToolStepTracker()
        try:
            async with self._client.beta.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield event.text
                    elif event.type == "content_block_stop":
                        step = steps.on_block(event.content_block)
                        if step is not None:
                            yield step
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
        tools: ToolOptions | None,
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
        definitions = tool_definitions(tools)
        if definitions:
            params["tools"] = definitions
            if tools is not None and not tools.enabled:
                params["tool_choice"] = {"type": "none"}  # declared but off: the tools cache still hits
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


def tool_definitions(tools: ToolOptions | None) -> list[dict[str, Any]]:
    """Server tool definitions in a fixed order: code execution, then web search (design.md §15).

    Client tools (propose_memory) join in week 4.
    """
    if tools is None:
        return []
    definitions: list[dict[str, Any]] = []
    if tools.code_execution:
        definitions.append(dict(CODE_EXECUTION_TOOL))
    if tools.web_search:
        definitions.append({"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": tools.web_search_max_uses})
    return definitions


class ToolStepTracker:
    """Turns finished content blocks into ToolSteps: a `server_tool_use` block starts a step,
    its matching result block (by `tool_use_id`) ends it. Other blocks are ignored."""

    def __init__(self) -> None:
        self.steps: dict[str, ToolStep] = {}

    def on_block(self, block: Any) -> ToolStep | None:
        if block.type == "server_tool_use":
            step = _started_step(block)
            if step is None:
                return None
            self.steps[step.id] = step
            return replace(step)
        running = self.steps.get(getattr(block, "tool_use_id", ""))
        if running is None or not block.type.endswith("_tool_result"):
            return None
        finished = _finished_step(running, block)
        self.steps[finished.id] = finished
        return replace(finished)

    def final_steps(self) -> list[ToolStep]:
        return [replace(step) for step in self.steps.values()]


def _started_step(block: Any) -> ToolStep | None:
    """A step as it starts. All code-running variants show as `code_execution`."""
    data = dict(block.input or {})
    if block.name == "web_search":
        return ToolStep(block.id, "web_search", "running", {"query": str(data.get("query", ""))})
    if block.name == "code_execution":
        return ToolStep(block.id, "code_execution", "running", {"code": str(data.get("code", ""))})
    if block.name == "bash_code_execution":
        return ToolStep(block.id, "code_execution", "running", {"code": str(data.get("command", "")), "language": "bash"})
    if block.name == "text_editor_code_execution":
        summary = " ".join(str(data[k]) for k in ("command", "path") if data.get(k))
        if data.get("file_text"):
            summary += "\n" + str(data["file_text"])
        return ToolStep(block.id, "code_execution", "running", {"code": summary, "language": "file"})
    return None  # e.g. web_fetch or advisor: not declared by mX


def _finished_step(running: ToolStep, block: Any) -> ToolStep:
    """The step's final state from its result block. Raw page content is never kept."""
    content = block.content
    error_code = getattr(content, "error_code", None)
    if error_code is not None:
        return replace(running, status="error", output=None, error_code=str(error_code))
    if block.type == "web_search_tool_result":
        sources = [{"url": r.url, "title": r.title} for r in (content or []) if getattr(r, "type", "") == "web_search_result"]
        return replace(running, status="ok", output={"sources": sources})
    if block.type in CODE_RESULT_TYPES and hasattr(content, "return_code"):
        return replace(running, status="ok",
                       output={"stdout": content.stdout, "stderr": content.stderr, "return_code": content.return_code})
    return replace(running, status="ok", output={})


def citations_of(response: BetaMessage) -> list[Citation]:
    """Web sources cited in the answer's text blocks, first mention first, no repeats."""
    seen: dict[str, Citation] = {}
    for block in response.content:
        if block.type != "text":
            continue
        for cite in getattr(block, "citations", None) or []:
            url = getattr(cite, "url", None)
            if getattr(cite, "type", "") == "web_search_result_location" and url and url not in seen:
                seen[url] = Citation(url, getattr(cite, "title", None) or url)
    return list(seen.values())


def visible_text(response: BetaMessage) -> str:
    """The answer's text blocks. Text that resumes after a tool step starts a new paragraph,
    the same rule /chat applies to the stream (design.md §5)."""
    text, after_tool = "", False
    for block in response.content:
        if block.type == "text":
            text += ("\n\n" if after_tool and text else "") + block.text
            after_tool = False
        elif block.type == "server_tool_use" or block.type.endswith("_tool_result"):
            after_tool = True
    return text


def to_model_response(response: BetaMessage, cache_ttl: str = "5m") -> ModelResponse:
    """Keep only the visible text; thinking blocks are internal to the model."""
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ProviderRefusalError("The model declined this request.", category=category)
    tracker = ToolStepTracker()
    for block in response.content:
        tracker.on_block(block)
    return ModelResponse(
        text=visible_text(response),
        model=response.model,
        stop_reason=response.stop_reason or "end_turn",
        tool_steps=tracker.final_steps(),
        citations=citations_of(response),
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
