"""Terminal client for quick prompt experiments: chat with mX, with streamed replies.

Run:   python try_mx.py          (normal mode: effort high)
       python try_mx.py brief    (brief mode: effort low, cheaper)
Quit:  Ctrl+C, or type "exit"

Each message costs real money (usually 1-3 cents in normal mode).
Talks to the provider directly (same prompt and mode settings as POST /chat) and saves nothing.
For normal use, run start-mx.ps1 and use the web app.
"""
import asyncio
import sys

from api.config import settings
from api.pricing import cost_usd
from api.prompts import MODE_OPTIONS, load_system_prompt
from providers import create_provider
from providers.base import Message, ModelResponse


def cost(reply: ModelResponse) -> str:
    usd = cost_usd(reply.model, reply.input_tokens, reply.output_tokens)
    return "cost unknown" if usd is None else f"~${usd:.4f}"


async def chat(mode: str) -> None:
    provider = create_provider(
        settings.primary_provider, api_key=settings.anthropic_api_key, model=settings.primary_model
    )
    prompt = load_system_prompt(mode, settings.system_prompt_file)
    history: list[Message] = []
    print(f"mX ({settings.primary_model}, {mode} mode, {prompt.version}). Type 'exit' to quit.")

    while True:
        user = input("\nYou: ").strip()
        if user.lower() in ("exit", "quit"):
            return
        if not user:
            continue
        history.append(Message(role="user", content=user))
        print("\nmX: ", end="", flush=True)
        async for item in provider.stream(history, prompt.text, **MODE_OPTIONS[mode]):
            if isinstance(item, str):
                print(item, end="", flush=True)
            else:
                history.append(Message(role="assistant", content=item.text))
                print(f"\n\n[{item.model} | {item.input_tokens} in / {item.output_tokens} out "
                      f"| {cost(item)} | stop: {item.stop_reason}]")


if __name__ == "__main__":
    chosen = sys.argv[1] if len(sys.argv) > 1 else "normal"
    if chosen not in MODE_OPTIONS:
        sys.exit(f"Mode must be one of: {', '.join(MODE_OPTIONS)}")
    try:
        asyncio.run(chat(chosen))
    except KeyboardInterrupt:
        print("\nBye.")
