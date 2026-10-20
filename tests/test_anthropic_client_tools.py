"""Anthropic adapter: the propose_memory round trip (design.md §6.1). SDK mocked, no cost."""
import asyncio

from providers.base import ClientTool, ClientToolResult, ModelResponse, ToolOptions, ToolStep
from tests.test_anthropic_pause import provider_for
from tests.test_anthropic_provider import HISTORY, make_message
from tests.test_anthropic_tools import tool_definitions

NOTE = "Rio is taking Calc II."


def tool(log: list[dict]) -> ClientTool:
    def run(raw: dict) -> ClientToolResult:
        log.append(raw)
        if raw.get("text") == "bad":
            return ClientToolResult("no", is_error=True)
        return ClientToolResult("Shown to Rio.", is_error=False)

    return ClientTool("propose_memory", "Remember a note.", {"type": "object"}, run)


def options(log: list[dict], enabled: bool = True) -> ToolOptions:
    return ToolOptions(enabled, True, True, 5, client_tools=(tool(log),))


def use(text: str, tool_id: str = "toolu_1") -> dict:
    return {"type": "tool_use", "id": tool_id, "name": "propose_memory", "input": {"text": text}}


def test_a_client_tool_runs_and_its_result_is_sent_back():
    log: list[dict] = []
    first = make_message([use(NOTE)], stop_reason="tool_use")
    done = make_message([{"type": "text", "text": "Save it if you want."}])
    provider, fake = provider_for([first, done])
    reply = asyncio.run(provider.generate(HISTORY, "sys", tools=options(log)))

    assert log == [{"text": NOTE}]
    assert len(fake.requests) == 2
    added = fake.requests[1]["messages"][-2:]
    assert added[0]["role"] == "assistant"
    assert added[0]["content"][0]["type"] == "tool_use"
    assert added[1] == {"role": "user", "content": [{
        "type": "tool_result", "tool_use_id": "toolu_1", "content": "Shown to Rio.", "is_error": False,
    }]}
    assert reply.text == "Save it if you want."
    assert [(step.status, step.output) for step in reply.tool_steps] == [("ok", {"text": "Shown to Rio."})]
    names = [item["name"] for item in fake.requests[0]["tools"]]
    assert names == ["code_execution", "web_search", "propose_memory"]
    assert fake.requests[0]["tools"][-1]["strict"] is True
    assert fake.requests[0]["tools"][-1]["eager_input_streaming"] is True


def test_client_rounds_stop_at_two_and_a_cutoff_never_runs():
    log: list[dict] = []
    rounds = [make_message([use(f"note {i}", f"toolu_{i}")], stop_reason="tool_use") for i in range(4)]
    provider, fake = provider_for(rounds)
    reply = asyncio.run(provider.generate(HISTORY, "sys", tools=options(log)))
    assert len(fake.requests) == 3  # two rounds, then the third tool_use ends the turn
    assert [raw["text"] for raw in log] == ["note 0", "note 1"]
    assert reply.stop_reason == "tool_use"

    log.clear()
    cut = make_message([use(NOTE)], stop_reason="max_tokens")
    provider, fake = provider_for([cut, make_message()])
    reply = asyncio.run(provider.generate(HISTORY, "sys", tools=options(log)))
    assert log == [] and len(fake.requests) == 1 and reply.stop_reason == "max_tokens"


def test_stream_yields_the_client_step():
    log: list[dict] = []
    first = make_message([use(NOTE)], stop_reason="tool_use")
    done = make_message([{"type": "text", "text": "Done."}])
    provider, _ = provider_for([first, done])

    async def collect() -> list:
        return [item async for item in provider.stream(HISTORY, "sys", tools=options(log))]

    items = asyncio.run(collect())
    steps = [item for item in items if isinstance(item, ToolStep)]
    assert [(step.status, step.input["text"]) for step in steps] == [("running", NOTE), ("ok", NOTE)]
    assert isinstance(items[-1], ModelResponse) and items[-1].tool_steps[-1].status == "ok"


def test_definitions_keep_the_client_tool_when_tools_are_disabled():
    on = options([])
    off = ToolOptions(False, True, True, 5, client_tools=on.client_tools)
    assert [item["name"] for item in tool_definitions(off)] == [item["name"] for item in tool_definitions(on)]
