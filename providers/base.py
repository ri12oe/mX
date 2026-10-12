"""Provider interface (design.md §6). Every model provider implements this.

The API layer only talks to `ModelProvider`; SDKs are used only inside
provider adapters such as providers/anthropic_provider.py.
"""
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class ImageData:
    media_type: str  # "image/jpeg" | "image/png" | "image/gif" | "image/webp"
    data: bytes


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str
    images: list[ImageData] | None = None  # only on the current turn's user message


@dataclass(frozen=True)
class SystemPart:
    """One piece of the system prompt; the prompt is a list of parts, in order (design.md §6.1)."""

    text: str
    cache: bool = False  # put a prompt-cache breakpoint after this part (§15)


@dataclass(frozen=True)
class ClientToolResult:
    text: str  # sent back to the model as the tool_result
    is_error: bool = False


@dataclass(frozen=True)
class ClientTool:
    """A tool mX runs itself (Phase 2: only propose_memory, design.md §18)."""

    name: str
    description: str  # loaded from prompts/tools/, never hardcoded
    input_schema: dict[str, Any]
    run: Callable[[dict[str, Any]], ClientToolResult]  # sync, fast, no network


@dataclass(frozen=True)
class ToolOptions:
    """Which tools a request may use (design.md §17)."""

    enabled: bool  # False: tools stay declared (cache-friendly) but the model may not call any
    code_execution: bool
    web_search: bool
    web_search_max_uses: int
    client_tools: tuple[ClientTool, ...] = ()


ToolStatus = Literal["running", "ok", "error"]


@dataclass
class ToolStep:
    """A tool step, yielded by `stream` when it starts (status "running") and again when it ends.

    Both yields carry the same `id`; the second has the final status and output.
    """

    id: str
    tool: str  # "code_execution" | "web_search" | a client tool name
    status: ToolStatus
    input: dict[str, Any]  # {"query"} | {"code"} | the client tool's input
    output: dict[str, Any] | None = None  # {sources} | {stdout, stderr, return_code} | client result
    error_code: str | None = None


@dataclass(frozen=True)
class Citation:
    url: str
    title: str


@dataclass
class ModelResponse:
    text: str
    model: str  # the model that actually answered (may differ after a fallback)
    input_tokens: int  # uncached input only (Anthropic's meaning)
    output_tokens: int
    stop_reason: str = "end_turn"  # "max_tokens" means the reply was cut off
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    web_searches: int = 0
    code_runs: int = 0
    requests: int = 1  # API requests behind this reply
    tool_steps: list[ToolStep] = field(default_factory=list)  # final state of each step, in order
    citations: list[Citation] = field(default_factory=list)  # sources the answer cited


@dataclass
class UsageMeter:
    """Running usage for one turn, updated by the adapter while it streams.

    Readable after an error or a cancelled stream, so a failed turn's spend
    can still be recorded (design.md §5, §6.1). A lower bound; the provider's
    console is the source of truth.
    """

    input_tokens: int = 0  # uncached input only
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    web_searches: int = 0
    code_runs: int = 0
    requests: int = 0
    model: str | None = None


SystemPrompt = str | list[SystemPart]  # a plain str means no cache breakpoints


@runtime_checkable
class ModelProvider(Protocol):
    name: str

    async def generate(
        self, messages: list[Message], system: SystemPrompt, **opts: Any
    ) -> ModelResponse:
        """Return the whole reply at once."""
        ...

    def stream(
        self, messages: list[Message], system: SystemPrompt, **opts: Any
    ) -> AsyncIterator[str | ToolStep | ModelResponse]:
        """Yield the reply as `str` chunks (and `ToolStep`s when tools run), then exactly one final `ModelResponse`.

        The final item carries the full text and token counts, so cost can be
        logged for streamed replies too. Nothing is yielded after it.
        Raises a `ProviderError` subclass on failure.

        Common options: `max_tokens`, `effort`, `cache_messages` (cache the
        conversation too, not just marked system parts), `cache_ttl` ("5m" or
        "1h"), and `meter` (a `UsageMeter` kept up to date while streaming).
        """
        ...
