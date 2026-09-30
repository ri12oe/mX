"""Quick manual test: chat with mX in the terminal, with streamed replies.

Run:   python try_mx.py          (normal mode: effort high)
       python try_mx.py brief    (brief mode: effort low, cheaper)
Quit:  Ctrl+C, or type "exit"

Each message costs real money (usually 1-3 cents in normal mode).
Temporary helper until POST /chat exists (Week 2, task 8). Not saved to the database.
"""
import asyncio
import sys
from pathlib import Path

from api.config import settings
from providers import create_provider
from providers.base import Message, ModelResponse

MODES = {"normal": {"max_tokens": 16000, "effort": "high"}, "brief": {"max_tokens": 2048, "effort": "low"}}
PRICE_PER_MTOK = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00)}  # USD in/out


def load_system_prompt(mode: str) -> str:
    return Path(settings.system_prompt_file).read_text(encoding="utf-8").replace("{mode}", mode)


def cost(reply: ModelResponse) -> str:
    prices = PRICE_PER_MTOK.get(reply.model)
    if prices is None:
        return "cost unknown"
    return f"~${reply.input_tokens * prices[0] / 1e6 + reply.output_tokens * prices[1] / 1e6:.4f}"


async def chat(mode: str) -> None:
    provider = create_provider(
        settings.primary_provider, api_key=settings.anthropic_api_key, model=settings.primary_model
    )
    system = load_system_prompt(mode)
    history: list[Message] = []
    print(f"mX ({settings.primary_model}, {mode} mode). Type 'exit' to quit.")

    while True:
        user = input("\nYou: ").strip()
        if user.lower() in ("exit", "quit"):
            return
        if not user:
            continue
        history.append(Message(role="user", content=user))
        print("\nmX: ", end="", flush=True)
        async for item in provider.stream(history, system, **MODES[mode]):
            if isinstance(item, str):
                print(item, end="", flush=True)
            else:
                history.append(Message(role="assistant", content=item.text))
                print(f"\n\n[{item.model} | {item.input_tokens} in / {item.output_tokens} out "
                      f"| {cost(item)} | stop: {item.stop_reason}]")


if __name__ == "__main__":
    chosen = sys.argv[1] if len(sys.argv) > 1 else "normal"
    if chosen not in MODES:
        sys.exit(f"Mode must be one of: {', '.join(MODES)}")
    try:
        asyncio.run(chat(chosen))
    except KeyboardInterrupt:
        print("\nBye.")
