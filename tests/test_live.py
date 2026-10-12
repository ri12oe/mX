"""Real-API smoke test (design.md §11). Costs about a cent.

Opt-in only:  pytest -m live
Skipped if ANTHROPIC_API_KEY isn't set.
"""
import asyncio

import pytest

from api.config import settings
from providers import create_provider
from providers.base import Message, ModelResponse, SystemPart, ToolOptions, ToolStep, UsageMeter

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not settings.anthropic_api_key, reason="ANTHROPIC_API_KEY not set"),
]

SMOKE_SYSTEM = "You are a connectivity check. Reply with exactly the word: pong"


def test_real_stream_round_trip():
    provider = create_provider(
        settings.primary_provider,
        api_key=settings.anthropic_api_key,
        model=settings.primary_model,
    )

    async def run() -> list[str | ModelResponse]:
        stream = provider.stream(
            [Message(role="user", content="ping")], SMOKE_SYSTEM,
            max_tokens=1024, effort="low",
        )
        return [item async for item in stream]

    items = asyncio.run(run())
    chunks, final = items[:-1], items[-1]

    assert chunks and all(isinstance(c, str) for c in chunks)
    assert isinstance(final, ModelResponse)
    assert "pong" in final.text.lower()
    assert final.text == "".join(chunks)
    assert final.model.startswith("claude-")
    assert final.input_tokens > 0 and final.output_tokens > 0
    assert final.stop_reason == "end_turn"

    print(f"\nlive: model={final.model} in={final.input_tokens} out={final.output_tokens} text={final.text!r}")


# Deterministic filler so the cached prefix is well over Opus 5.5's 512-token minimum (~1,500 tokens).
CACHE_REFERENCE = "\n".join(
    f"Reference line {i}: the value of item {i} is {i * 7 % 101}, filed under group {i % 9}."
    for i in range(1, 121)
)


def test_real_prompt_cache_hit_on_second_identical_request():
    """Design §15: the same prefix sent twice is read from the cache the second time. About $0.01–0.02."""
    provider = create_provider(
        settings.primary_provider,
        api_key=settings.anthropic_api_key,
        model=settings.primary_model,
    )
    system = [SystemPart(SMOKE_SYSTEM + "\n\n" + CACHE_REFERENCE, cache=True)]
    messages = [Message(role="user", content="ping")]

    async def run(meter: UsageMeter) -> ModelResponse:
        items = [item async for item in provider.stream(
            messages, system, max_tokens=1024, effort="low", cache_messages=True, meter=meter,
        )]
        final = items[-1]
        assert isinstance(final, ModelResponse)
        return final

    first_meter, second_meter = UsageMeter(), UsageMeter()
    first = asyncio.run(run(first_meter))
    second = asyncio.run(run(second_meter))

    assert first.cache_write_5m_tokens + first.cache_read_tokens > 0  # written now, or still warm from a recent run
    assert second.cache_read_tokens > 0
    assert second.cache_read_tokens > second.input_tokens  # most of the prompt came from the cache
    assert (second_meter.cache_read_tokens, second_meter.output_tokens) == (second.cache_read_tokens, second.output_tokens)

    for label, r in (("first", first), ("second", second)):
        print(f"\nlive cache {label}: in={r.input_tokens} write5m={r.cache_write_5m_tokens} "
              f"read={r.cache_read_tokens} out={r.output_tokens}")


CODE_SYSTEM = (
    "You are a test harness. When asked to compute something, run Python with the code execution "
    "tool, then reply with only the exact result."
)


def test_real_code_execution_and_tools_off():
    """Design §17: a real code run returns 2^100; with tools off, tool_choice none is accepted
    alongside server tools and nothing runs. About $0.02–0.05 (code execution itself is free
    within the monthly allowance)."""
    provider = create_provider(
        settings.primary_provider,
        api_key=settings.anthropic_api_key,
        model=settings.primary_model,
    )
    on = ToolOptions(enabled=True, code_execution=True, web_search=False, web_search_max_uses=1)
    off = ToolOptions(enabled=False, code_execution=True, web_search=False, web_search_max_uses=1)
    ask = [Message(role="user", content="Compute 2**100 using the code execution tool.")]

    async def run(tools: ToolOptions) -> list[str | ToolStep | ModelResponse]:
        return [item async for item in provider.stream(ask, CODE_SYSTEM, max_tokens=4096, effort="low", tools=tools)]

    items = asyncio.run(run(on))
    final = items[-1]
    assert isinstance(final, ModelResponse)
    steps = [i for i in items if isinstance(i, ToolStep)]
    assert any(s.tool == "code_execution" and s.status == "running" for s in steps)
    ran = [s for s in final.tool_steps if s.tool == "code_execution" and s.status == "ok"]
    assert ran and "1267650600228229401496703205376" in (ran[-1].output or {}).get("stdout", "")
    assert "1267650600228229401496703205376" in final.text
    assert final.code_runs >= 1

    off_items = asyncio.run(run(off))  # the API accepts tool_choice none with server tools
    off_final = off_items[-1]
    assert isinstance(off_final, ModelResponse)
    assert off_final.tool_steps == [] and off_final.code_runs == 0

    print(f"\nlive code: requests={final.requests} in={final.input_tokens} out={final.output_tokens} "
          f"code_runs={final.code_runs} steps={[(s.tool, s.status) for s in final.tool_steps]}")
    print(f"live tools off: in={off_final.input_tokens} out={off_final.output_tokens} text={off_final.text[:80]!r}")


SEARCH_SYSTEM = (
    "You are a test harness. Answer current-events questions by searching the web first, "
    "cite your sources, and keep the answer to two sentences."
)


def test_real_web_search_with_citations():
    """Design §17: a real search returns sources (url + title only) and a cited answer; the
    search is counted and its $0.01 fee priced. About $0.03–0.10 (search results are input tokens)."""
    provider = create_provider(
        settings.primary_provider,
        api_key=settings.anthropic_api_key,
        model=settings.primary_model,
    )
    search_only = ToolOptions(enabled=True, code_execution=False, web_search=True, web_search_max_uses=2)
    ask = [Message(role="user", content="What is the latest stable release of Python right now? Search the web.")]

    async def run() -> list[str | ToolStep | ModelResponse]:
        return [item async for item in provider.stream(ask, SEARCH_SYSTEM, max_tokens=4096, effort="low", tools=search_only)]

    items = asyncio.run(run())
    final = items[-1]
    assert isinstance(final, ModelResponse)
    searches = [s for s in final.tool_steps if s.tool == "web_search"]
    assert searches and searches[0].input.get("query")
    ok = [s for s in searches if s.status == "ok"]
    assert ok and ok[0].output and ok[0].output["sources"]
    assert all(set(src) == {"url", "title"} for src in ok[0].output["sources"])  # never page content
    assert 1 <= final.web_searches <= 2
    assert final.citations and all(c.url.startswith("http") for c in final.citations)

    from api.pricing import cost_usd
    cost = cost_usd(final.model, final.input_tokens, final.output_tokens,
                    cache_read_tokens=final.cache_read_tokens, cache_write_5m_tokens=final.cache_write_5m_tokens,
                    web_searches=final.web_searches)
    print(f"\nlive search: requests={final.requests} in={final.input_tokens} out={final.output_tokens} "
          f"searches={final.web_searches} citations={len(final.citations)} cost=${cost:.4f}")
    print(f"live search answer: {final.text[:200]!r}")
    print(f"live search sources: {[s['title'] for s in ok[0].output['sources'][:3]]}")
