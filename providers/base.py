"""Provider interface. Every model provider implements this.

Week 2 task: implement an adapter (e.g. providers/anthropic_provider.py).
"""
from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str
    images: list[str] | None = None  # base64 strings (Week 3)


@dataclass
class ModelResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class ModelProvider(Protocol):
    name: str

    async def generate(
        self, messages: list[Message], system: str, **opts
    ) -> ModelResponse: ...

    def stream(
        self, messages: list[Message], system: str, **opts
    ) -> AsyncIterator[str]: ...
