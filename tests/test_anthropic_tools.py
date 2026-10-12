"""Anthropic adapter: tool definitions and tool steps from the stream (design.md §6.1, §17).

The SDK is mocked; content blocks are built with the SDK's own models so their shapes are real.
"""
import asyncio
from typing import Any

import pytest
from anthropic.types.beta import BetaMessage

from providers.anthropic_provider import CODE_EXECUTION_TOOL, WEB_SEARCH_TOOL_TYPE, tool_definitions
from providers.base import Citation, ModelResponse, ToolOptions, ToolStep
from tests.test_anthropic_provider import HISTORY, FakeStream, collect, make_message, provider_with, streaming_provider

ALL_TOOLS = ToolOptions(enabled=True, code_execution=True, web_search=True, web_search_max_uses=5)

CODE_USE = {"type": "server_tool_use", "id": "srvtoolu_1", "name": "bash_code_execution",
            "input": {"command": "python3 -c 'print(2**100)'"}}
CODE_RESULT = {"type": "bash_code_execution_tool_result", "tool_use_id": "srvtoolu_1",
               "content": {"type": "bash_code_execution_result", "stdout": "1267650600228229401496703205376\n",
                           "stderr": "", "return_code": 0, "content": []}}
SEARCH_USE = {"type": "server_tool_use", "id": "srvtoolu_2", "name": "web_search",
              "input": {"query": "Python 3.14 release date"}}
SEARCH_RESULT = {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_2", "content": [
    {"type": "web_search_result", "url": "https://www.python.org/downloads/", "title": "Python downloads",
     "encrypted_content": "ZW5jcnlwdGVk", "page_age": None},
    {"type": "web_search_result", "url": "https://docs.python.org/3/whatsnew/", "title": "What's New",
     "encrypted_content": "ZW5jcnlwdGVk", "page_age": "2 days ago"},
]}
CITED_TEXT = {"type": "text", "text": "Python 3.14 was released in October 2025.", "citations": [
    {"type": "web_search_result_location", "url": "https://www.python.org/downloads/", "title": "Python downloads",
     "encrypted_index": "aW5kZXg=", "cited_text": "Python 3.14.0 released"},
    {"type": "web_search_result_location", "url": "https://www.python.org/downloads/", "title": "Python downloads",
     "encrypted_index": "aW5kZXg=", "cited_text": "again"},
]}


def message_with(*content: dict[str, Any], **extra: Any) -> BetaMessage:
    return make_message(content=list(content), **extra)


def blocks(message: BetaMessage, *types: str) -> list[Any]:
    return [b for b in message.content if b.type in types]


# --- Tool definitions ---------------------------------------------------------


def test_no_tools_means_no_tools_key():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, "sys"))
    assert "tools" not in fake.kwargs and "tool_choice" not in fake.kwargs


def test_tools_are_declared_in_a_fixed_order():
    provider, fake = provider_with(make_message())
    asyncio.run(provider.generate(HISTORY, "sys", tools=ALL_TOOLS))
    assert fake.kwargs["tools"] == [
        {"type": "code_execution_20260120", "name": "code_execution"},
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    ]
    assert "tool_choice" not in fake.kwargs  # the model decides (Rio's choice, §17)


def test_tools_off_keeps_definitions_and_sends_tool_choice_none():
    """Same definitions as with tools on, so the cached prefix is unchanged (§15)."""
    provider, fake = streaming_provider(FakeStream(["ok"], make_message()))
    off = ToolOptions(enabled=False, code_execution=True, web_search=True, web_search_max_uses=5)
    asyncio.run(collect(provider.stream(HISTORY, "sys", tools=off)))
    assert fake.kwargs["tools"] == tool_definitions(ALL_TOOLS)
    assert fake.kwargs["tool_choice"] == {"type": "none"}


@pytest.mark.parametrize(
    ("options", "names"),
    [
        (ToolOptions(True, code_execution=True, web_search=False, web_search_max_uses=5), ["code_execution"]),
        (ToolOptions(True, code_execution=False, web_search=True, web_search_max_uses=2), ["web_search"]),
        (ToolOptions(True, code_execution=False, web_search=False, web_search_max_uses=5), []),
    ],
)
def test_each_tool_can_be_left_out(options: ToolOptions, names: list[str]):
    assert [d["name"] for d in tool_definitions(options)] == names
    assert CODE_EXECUTION_TOOL["type"].startswith("code_execution_") and WEB_SEARCH_TOOL_TYPE.startswith("web_search_")


# --- Steps from the stream ----------------------------------------------------


def test_text_only_stream_is_unchanged():
    final = make_message([{"type": "text", "text": "Hello, Rio."}])
    items = asyncio.run(collect(streaming_provider(FakeStream(["Hello", ", ", "Rio."], final))[0].stream(HISTORY, "sys")))
    assert items[:-1] == ["Hello", ", ", "Rio."]
    last = items[-1]
    assert isinstance(last, ModelResponse) and (last.tool_steps, last.citations) == ([], [])


def test_a_code_step_is_yielded_when_it_starts_and_when_it_ends():
    final = message_with({"type": "text", "text": "Let me compute that."}, CODE_USE, CODE_RESULT,
                         {"type": "text", "text": "It is 1267650600228229401496703205376."})
    stream = FakeStream(["Let me compute that.", None, None, "It is 1267650600228229401496703205376."], final,
                        blocks=blocks(final, "server_tool_use", "bash_code_execution_tool_result"))
    items = asyncio.run(collect(streaming_provider(stream)[0].stream(HISTORY, "sys", tools=ALL_TOOLS)))

    assert items[0] == "Let me compute that."
    assert items[1] == ToolStep("srvtoolu_1", "code_execution", "running",
                                {"code": "python3 -c 'print(2**100)'", "language": "bash"})
    assert items[2] == ToolStep("srvtoolu_1", "code_execution", "ok", {"code": "python3 -c 'print(2**100)'", "language": "bash"},
                                {"stdout": "1267650600228229401496703205376\n", "stderr": "", "return_code": 0})
    assert items[3] == "It is 1267650600228229401496703205376."
    last = items[-1]
    assert isinstance(last, ModelResponse)
    assert last.text == "Let me compute that.\n\nIt is 1267650600228229401496703205376."
    assert last.tool_steps == [items[2]]


def test_a_search_step_keeps_sources_but_never_page_content():
    final = message_with(SEARCH_USE, SEARCH_RESULT, CITED_TEXT)
    stream = FakeStream([None, None, CITED_TEXT["text"]], final,
                        blocks=blocks(final, "server_tool_use", "web_search_tool_result"))
    items = asyncio.run(collect(streaming_provider(stream)[0].stream(HISTORY, "sys", tools=ALL_TOOLS)))
    started, ended = items[0], items[1]
    assert started == ToolStep("srvtoolu_2", "web_search", "running", {"query": "Python 3.14 release date"})
    assert isinstance(ended, ToolStep) and ended.status == "ok"
    assert ended.output == {"sources": [
        {"url": "https://www.python.org/downloads/", "title": "Python downloads"},
        {"url": "https://docs.python.org/3/whatsnew/", "title": "What's New"},
    ]}
    last = items[-1]
    assert isinstance(last, ModelResponse)
    assert last.citations == [Citation("https://www.python.org/downloads/", "Python downloads")]  # cited twice, listed once


@pytest.mark.parametrize(
    ("use", "result", "error_code"),
    [
        (SEARCH_USE, {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_2",
                      "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}},
         "max_uses_exceeded"),
        (CODE_USE, {"type": "bash_code_execution_tool_result", "tool_use_id": "srvtoolu_1",
                    "content": {"type": "bash_code_execution_tool_result_error", "error_code": "execution_time_exceeded"}},
         "execution_time_exceeded"),
    ],
)
def test_tool_errors_end_the_step_with_its_error_code(use: dict, result: dict, error_code: str):
    final = message_with(use, result, {"type": "text", "text": "That didn't work."})
    stream = FakeStream([None, None, "That didn't work."], final, blocks=final.content[:2])
    items = asyncio.run(collect(streaming_provider(stream)[0].stream(HISTORY, "sys", tools=ALL_TOOLS)))
    ended = items[1]
    assert isinstance(ended, ToolStep)
    assert (ended.status, ended.error_code, ended.output) == ("error", error_code, None)


def test_a_failing_program_is_still_an_ok_step_with_its_exit_code():
    result = {**CODE_RESULT, "content": {"type": "bash_code_execution_result", "stdout": "",
                                         "stderr": "ZeroDivisionError", "return_code": 1, "content": []}}
    final = message_with(CODE_USE, result)
    reply = asyncio.run(provider_with(final)[0].generate(HISTORY, "sys", tools=ALL_TOOLS))
    assert reply.tool_steps[0].status == "ok"
    assert reply.tool_steps[0].output == {"stdout": "", "stderr": "ZeroDivisionError", "return_code": 1}


def test_python_and_file_editing_variants_show_as_code_execution():
    final = message_with(
        {"type": "server_tool_use", "id": "a", "name": "code_execution", "input": {"code": "print(1)"}},
        {"type": "server_tool_use", "id": "b", "name": "text_editor_code_execution",
         "input": {"command": "create", "path": "/tmp/x.py", "file_text": "print(2)"}},
    )
    reply = asyncio.run(provider_with(final)[0].generate(HISTORY, "sys", tools=ALL_TOOLS))
    assert [(s.tool, s.input, s.status) for s in reply.tool_steps] == [
        ("code_execution", {"code": "print(1)"}, "running"),
        ("code_execution", {"code": "create /tmp/x.py\nprint(2)", "language": "file"}, "running"),
    ]


def test_undeclared_server_tools_and_orphan_results_are_ignored():
    final = message_with(
        {"type": "server_tool_use", "id": "f", "name": "web_fetch", "input": {"url": "https://example.com"}},
        SEARCH_RESULT,  # no matching server_tool_use
        {"type": "text", "text": "ok"},
    )
    reply = asyncio.run(provider_with(final)[0].generate(HISTORY, "sys", tools=ALL_TOOLS))
    assert reply.tool_steps == [] and reply.text == "ok"


def test_generate_reports_steps_citations_and_paragraph_breaks():
    final = message_with({"type": "text", "text": "Searching."}, SEARCH_USE, SEARCH_RESULT, CITED_TEXT)
    reply = asyncio.run(provider_with(final)[0].generate(HISTORY, "sys", tools=ALL_TOOLS))
    assert reply.text == "Searching.\n\n" + CITED_TEXT["text"]
    assert [s.status for s in reply.tool_steps] == ["ok"]
    assert reply.citations == [Citation("https://www.python.org/downloads/", "Python downloads")]


def test_code_runs_and_searches_are_counted_from_steps_when_usage_omits_them():
    """design.md §9.1: usage.server_tool_use is preferred; otherwise count the steps."""
    failed_search = {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_3",
                     "content": {"type": "web_search_tool_result_error", "error_code": "unavailable"}}
    final = message_with(CODE_USE, CODE_RESULT, SEARCH_USE, SEARCH_RESULT,
                         {**SEARCH_USE, "id": "srvtoolu_3"}, failed_search)
    reply = asyncio.run(provider_with(final)[0].generate(HISTORY, "sys", tools=ALL_TOOLS))
    assert (reply.code_runs, reply.web_searches) == (1, 1)  # the failed search isn't billed


def test_usage_counts_win_over_counting_steps():
    final = message_with(SEARCH_USE, SEARCH_RESULT, usage={"input_tokens": 1, "output_tokens": 1,
                                                          "server_tool_use": {"web_search_requests": 3, "web_fetch_requests": 0}})
    reply = asyncio.run(provider_with(final)[0].generate(HISTORY, "sys", tools=ALL_TOOLS))
    assert reply.web_searches == 3
