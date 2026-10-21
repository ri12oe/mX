"""Tool steps through /chat: SSE events, paragraph breaks, saving (design.md §5, §6.1). FakeProvider, no cost."""
import asyncio
import json
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import chat as chat_module
from api import db
from api.config import settings
from api.main import app, get_db, get_provider
from providers.base import Citation, ModelResponse, ToolStep
from providers.errors import ProviderUnavailableError
from tests.fakes import FakeProvider
from tests.test_chat import HEADERS, parse_sse

CODE = "print(2**100)"
RUN = ToolStep("t1", "code_execution", "running", {"code": CODE})
RAN = ToolStep("t1", "code_execution", "ok", {"code": CODE},
               {"stdout": "1267650600228229401496703205376\n", "stderr": "", "return_code": 0})
SEARCH = ToolStep("t2", "web_search", "running", {"query": "Python 3.14 release date"})
SEARCHED = ToolStep("t2", "web_search", "ok", {"query": "Python 3.14 release date"},
                    {"sources": [{"url": "https://www.python.org/downloads/", "title": "Python downloads",
                                  "page_content": "should never be stored"}]})


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider(model="claude-opus-5-5", input_tokens=500, output_tokens=40)


@pytest.fixture
def client(conn: sqlite3.Connection, fake: FakeProvider) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_provider] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


def chat(client: TestClient, **body: Any) -> list[tuple[str, dict[str, Any]]]:
    r = client.post("/chat", json={"message": "Compute 2^100", **body}, headers=HEADERS)
    assert r.status_code == 200
    return parse_sse(r.text)


def test_tool_events_stream_in_order(client: TestClient, fake: FakeProvider):
    fake.script = ["Let me compute that.", RUN, RAN, "It is 1267650600228229401496703205376."]
    events = chat(client)
    assert [name for name, _ in events] == ["meta", "delta", "tool_start", "tool_end", "delta", "done"]
    start, end = events[2][1], events[3][1]
    assert start == {"step_id": "t1", "tool": "code_execution", "input": {"code": CODE}}
    assert end["status"] == "ok" and end["error_code"] is None
    assert end["output"]["stdout"].startswith("126765") and end["output"]["return_code"] == 0


def test_text_after_a_tool_step_starts_a_new_paragraph(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    fake.script = ["Let me compute that.", RUN, RAN, "It is ", "big."]
    events = chat(client)
    deltas = [data["text"] for name, data in events if name == "delta"]
    assert deltas == ["Let me compute that.", "\n\nIt is ", "big."]
    saved = conn.execute("SELECT content FROM messages WHERE role = 'assistant'").fetchone()[0]
    assert saved == "Let me compute that.\n\nIt is big."  # the saved text is exactly what streamed


def test_no_break_when_a_reply_starts_with_a_tool(client: TestClient, fake: FakeProvider):
    fake.script = [RUN, RAN, "Done."]
    deltas = [data["text"] for name, data in chat(client) if name == "delta"]
    assert deltas == ["Done."]


def test_steps_and_citations_are_saved_with_the_turn(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    fake.script = [SEARCH, SEARCHED, "Python 3.14 is out.", RUN, RAN, "And 2^100 is big."]
    fake.citations = [Citation("https://www.python.org/downloads/", "Python downloads")]
    events = chat(client)
    done = events[-1][1]
    assert done["citations"] == [{"url": "https://www.python.org/downloads/", "title": "Python downloads"}]
    assert (done["usage"]["web_searches"], done["usage"]["code_runs"]) == (1, 1)

    convo = db.get_conversation(conn, events[0][1]["conversation_id"])
    assert convo is not None
    reply = convo["messages"][1]
    assert [(s["seq"], s["tool"], s["status"]) for s in reply["tool_steps"]] == [
        (0, "web_search", "ok"), (1, "code_execution", "ok")]
    assert reply["tool_steps"][0]["output"]["sources"] == [
        {"url": "https://www.python.org/downloads/", "title": "Python downloads"}]  # no page content
    assert reply["citations"] == done["citations"]
    usage = conn.execute("SELECT web_searches, code_runs FROM usage").fetchone()
    assert tuple(usage) == (1, 1)


def test_a_failed_tool_step_is_shown_and_saved(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    failed = ToolStep("t2", "web_search", "error", {"query": "x"}, None, "unavailable")
    fake.script = [SEARCH, failed, "Search is down, so from memory: ..."]
    events = chat(client)
    end = next(data for name, data in events if name == "tool_end")
    assert (end["status"], end["error_code"], end["output"]) == ("error", "unavailable", {})
    step = conn.execute("SELECT status, error_code FROM tool_steps").fetchone()
    assert tuple(step) == ("error", "unavailable")


def test_a_step_still_running_at_the_end_is_saved_as_incomplete(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    fake.script = [RUN, "Ran out of room."]
    chat(client)
    assert tuple(conn.execute("SELECT status, error_code FROM tool_steps").fetchone()) == ("error", "incomplete")


def test_long_code_is_clipped_in_the_event(client: TestClient, fake: FakeProvider):
    long_code = "x = 1\n" * 2_000  # 12,000 chars
    fake.script = [ToolStep("t1", "code_execution", "running", {"code": long_code}), "ok"]
    start = next(data for name, data in chat(client) if name == "tool_start")
    assert len(start["input"]["code"]) == db.MAX_CODE_CHARS and start["input"]["code_truncated"] is True


def test_client_tool_steps_are_a_suggestion_and_not_saved(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    """propose_memory becomes a memory suggestion, never a stored step (design.md §18)."""
    fake.script = [ToolStep("m1", "propose_memory", "running", {"text": "Rio takes Calc II"}),
                   ToolStep("m1", "propose_memory", "ok", {"text": "Rio takes Calc II"}), "Noted."]
    events = chat(client)
    assert [name for name, _ in events] == ["meta", "memory_suggestion", "delta", "done"]
    assert events[1][1] == {"suggestion_id": "m1", "text": "Rio takes Calc II"}
    assert conn.execute("SELECT COUNT(*) FROM tool_steps").fetchone()[0] == 0


def test_mid_stream_failure_after_a_tool_step_saves_no_steps(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    fake.script = [RUN, RAN, "partial"]
    fake.error, fake.fail_after = ProviderUnavailableError("lost"), 2
    events = chat(client)
    assert [name for name, _ in events] == ["meta", "tool_start", "tool_end", "error"]
    assert conn.execute("SELECT COUNT(*) FROM tool_steps").fetchone()[0] == 0
    assert conn.execute("SELECT status FROM usage").fetchone()[0] == "failed"


class SlowToolProvider:
    """Starts a tool right away, then takes a while (like a long code run) before any text."""

    name = "slow-tool"

    async def generate(self, messages: Any, system: Any, **opts: Any) -> Any:
        raise NotImplementedError

    async def stream(self, messages: Any, system: Any, **opts: Any):
        yield RUN
        await asyncio.sleep(0.3)
        yield RAN
        yield "Done."
        yield ModelResponse(text="Done.", model="claude-opus-5-5", input_tokens=1, output_tokens=1, tool_steps=[RAN])


def test_a_tool_event_counts_as_the_first_item_for_fail_fast(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch):
    """The stream starts as soon as a tool step begins; the long run is covered by heartbeats."""
    monkeypatch.setattr(chat_module, "FIRST_ITEM_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(chat_module, "HEARTBEAT_SECONDS", 0.05)
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_provider] = lambda: SlowToolProvider()
    try:
        r = TestClient(app).post("/chat", json={"message": "Run something slow"}, headers=HEADERS)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.text.index("event: tool_start") < r.text.index(": ping") < r.text.index("event: tool_end")
    assert [name for name, _ in parse_sse(r.text)] == ["meta", "tool_start", "tool_end", "delta", "done"]


# --- Code execution switched on (task 14) -------------------------------------


def test_code_execution_and_web_search_are_offered_by_default(client: TestClient, fake: FakeProvider):
    meta = chat(client)[0][1]
    tools = fake.calls[0].opts["tools"]
    assert (tools.enabled, tools.code_execution, tools.web_search, tools.web_search_max_uses) == (True, True, True, 5)
    assert meta["tools"] is True


def test_toggle_off_keeps_the_definitions_but_disables_them(client: TestClient, fake: FakeProvider):
    """Same definitions as with the toggle on, so the cache holds (design.md §15)."""
    meta = chat(client, tools=False)[0][1]
    tools = fake.calls[0].opts["tools"]
    assert (tools.enabled, tools.code_execution) == (False, True)
    assert meta["tools"] is False


def test_budget_brief_mode_turns_tools_off(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    db.save_spend(conn, db.UsageRecord("anthropic", "claude-opus-5-5", "v", 1, 1, 25.0, 1))
    meta = chat(client)[0][1]
    assert (meta["mode"], meta["tools"]) == ("brief", False)
    assert fake.calls[0].opts["tools"].enabled is False


def test_tools_disabled_server_wide_declares_nothing(client: TestClient, fake: FakeProvider, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "tools_enabled", False)
    meta = chat(client)[0][1]
    assert fake.calls[0].opts["tools"] is None
    assert meta["tools"] is False
    assert client.get("/whoami", headers=HEADERS).json()["tools_enabled"] is False


def test_whoami_reports_tools_enabled(client: TestClient):
    assert client.get("/whoami", headers=HEADERS).json()["tools_enabled"] is True


@pytest.mark.parametrize(
    ("ended", "expected"),
    [
        (RAN, ("ok", None, 0)),
        (ToolStep("t1", "code_execution", "ok", {"code": CODE},
                  {"stdout": "", "stderr": "ZeroDivisionError: division by zero", "return_code": 1}), ("ok", None, 1)),
        (ToolStep("t1", "code_execution", "error", {"code": CODE}, None, "execution_time_exceeded"),
         ("error", "execution_time_exceeded", None)),
    ],
    ids=["success", "non-zero exit", "tool error"],
)
def test_code_runs_are_saved_and_counted(
    client: TestClient, conn: sqlite3.Connection, fake: FakeProvider, ended: ToolStep, expected: tuple,
):
    fake.script = [RUN, ended, "Here's what happened."]
    done = chat(client)[-1][1]
    step = conn.execute("SELECT status, error_code, output FROM tool_steps").fetchone()
    return_code = None if step["output"] is None else json.loads(step["output"])["return_code"]
    assert (step["status"], step["error_code"], return_code) == expected
    assert done["usage"]["code_runs"] == 1
    assert conn.execute("SELECT code_runs FROM usage").fetchone()[0] == 1


# --- Web search switched on (task 16) -----------------------------------------


def test_search_cap_comes_from_the_setting(client: TestClient, fake: FakeProvider, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "web_search_max_uses", 2)
    chat(client)
    assert fake.calls[0].opts["tools"].web_search_max_uses == 2


@pytest.mark.parametrize("value", [0, 21])
def test_search_cap_setting_is_checked(value: int):
    from api.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="WEB_SEARCH_MAX_USES"):
        Settings(web_search_max_uses=value)


def test_search_sources_stream_in_tool_end(client: TestClient, fake: FakeProvider):
    fake.script = [SEARCH, SEARCHED, "Python 3.14 is out."]
    end = next(data for name, data in chat(client) if name == "tool_end")
    assert end["tool"] == "web_search"
    assert end["output"] == {"sources": [{"url": "https://www.python.org/downloads/", "title": "Python downloads"}]}


def test_citations_are_deduplicated_in_done_and_saved(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    docs = Citation("https://docs.python.org/3/", "Python docs")
    downloads = Citation("https://www.python.org/downloads/", "Python downloads")
    fake.script = [SEARCH, SEARCHED, "Answer with sources."]
    fake.citations = [downloads, docs, Citation(downloads.url, "Same page, another title"), docs]
    events = chat(client)
    done = events[-1][1]
    assert done["citations"] == [{"url": downloads.url, "title": "Python downloads"},
                                 {"url": docs.url, "title": "Python docs"}]
    saved = db.get_conversation(conn, events[0][1]["conversation_id"])["messages"][1]["citations"]  # type: ignore[index]
    assert saved == done["citations"]


def test_a_failed_search_is_an_error_chip_and_not_billed(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    failed = ToolStep("t2", "web_search", "error", {"query": "x"}, None, "too_many_requests")
    fake.script = [SEARCH, failed, "Search is busy; here's what I know."]
    events = chat(client)
    end = next(data for name, data in events if name == "tool_end")
    assert (end["status"], end["error_code"]) == ("error", "too_many_requests")
    assert events[-1][1]["usage"]["web_searches"] == 0
    assert conn.execute("SELECT web_searches FROM usage").fetchone()[0] == 0


def test_search_fee_is_in_the_cost(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    """500 in × $4 + 40 out × $20 per million = $0.0028, plus 2 searches × $0.01."""
    other = ToolStep("t3", "web_search", "ok", {"query": "q2"}, {"sources": []})
    fake.script = [SEARCH, SEARCHED, ToolStep("t3", "web_search", "running", {"query": "q2"}), other, "Done."]
    done = chat(client)[-1][1]
    assert done["usage"]["web_searches"] == 2
    assert done["usage"]["cost_usd"] == pytest.approx(0.0028 + 0.02)
    assert conn.execute("SELECT cost_usd FROM usage").fetchone()[0] == pytest.approx(0.0228)


# --- Phase 2 wrap-up: tools-off note and the empty-reply guard ----------------


def test_tools_off_adds_a_note_to_the_message_sent_but_not_the_one_saved(
    client: TestClient, conn: sqlite3.Connection, fake: FakeProvider,
):
    chat(client, message="Who won the most recent World Cup?", tools=False)
    sent = fake.calls[0].messages[-1].content
    assert sent.startswith("Who won the most recent World Cup?")
    assert "code execution and web search are off" in sent and "<!--" not in sent
    saved = conn.execute("SELECT content FROM messages WHERE role = 'user'").fetchone()[0]
    assert saved == "Who won the most recent World Cup?"  # exactly what Rio typed


def test_tools_on_sends_the_message_unchanged(client: TestClient, fake: FakeProvider):
    chat(client, message="Who won the most recent World Cup?")
    assert fake.calls[0].messages[-1].content == "Who won the most recent World Cup?"


def test_budget_brief_mode_also_adds_the_note(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    db.save_spend(conn, db.UsageRecord("anthropic", "claude-opus-5-5", "v", 1, 1, 25.0, 1))
    chat(client)
    assert "are off for this message" in fake.calls[0].messages[-1].content


def test_an_empty_reply_is_an_error_and_never_saved(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    """Eval p59 (2026-10-20): with tools off the model ended its turn with only hidden thinking."""
    fake.chunks = []
    events = chat(client, tools=False)
    assert events[-1] == ("error", {"code": "empty_reply",
                                    "message": "mX finished without writing an answer. Please try again."})
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert tuple(conn.execute("SELECT status, message_id FROM usage").fetchone()) == ("failed", None)  # spend counts


def test_a_reply_with_only_tool_steps_and_no_text_is_also_an_error(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    fake.script = [RUN, RAN]
    assert chat(client)[-1][1]["code"] == "empty_reply"
    assert conn.execute("SELECT COUNT(*) FROM tool_steps").fetchone()[0] == 0
