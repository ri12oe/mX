"""Tool steps through /chat: SSE events, paragraph breaks, saving (design.md §5, §6.1). FakeProvider, no cost."""
import asyncio
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import chat as chat_module
from api import db
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


def test_client_tool_steps_are_not_shown_or_saved(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    """propose_memory is a client tool: week 4 turns it into a memory suggestion, never a stored step."""
    fake.script = [ToolStep("m1", "propose_memory", "running", {"text": "Rio takes Calc II"}),
                   ToolStep("m1", "propose_memory", "ok", {"text": "Rio takes Calc II"}), "Noted."]
    assert [name for name, _ in chat(client)] == ["meta", "delta", "done"]
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
