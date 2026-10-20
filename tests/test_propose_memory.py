"""propose_memory: validation, no database write, and the suggestion event (design.md §18)."""
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_db, get_provider
from api.tools import propose_memory_tool
from providers.base import ToolStep
from tests.fakes import FakeProvider
from tests.test_chat import HEADERS, parse_sse


def test_one_valid_proposal_per_turn_and_nothing_is_stored(conn: sqlite3.Connection):
    tool = propose_memory_tool()
    ok = tool.run({"text": "  Rio is taking Calc II.  "})
    assert ok.is_error is False and "approve" in ok.text
    again = tool.run({"text": "Rio prefers Python."})
    assert again.is_error is True and again.text == "limit reached"
    bad = propose_memory_tool().run({"text": "   "})
    assert bad.is_error is True
    assert propose_memory_tool().run({"text": "x" * 201}).is_error is True
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM tool_steps").fetchone()[0] == 0


@pytest.fixture
def client(conn: sqlite3.Connection) -> Iterator[TestClient]:
    fake = FakeProvider(model="claude-opus-5-5")
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_provider] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_an_accepted_proposal_is_a_suggestion_and_is_not_saved(client: TestClient, conn: sqlite3.Connection):
    fake = app.dependency_overrides[get_provider]()
    note = "Rio is taking Calc II this semester."
    fake.script = [
        "Want me to remember that?",
        ToolStep("s1", "propose_memory", "running", {"text": note}),
        ToolStep("s1", "propose_memory", "ok", {"text": note}, {"text": "Shown to Rio."}),
        "Only if you save it.",
    ]
    response = client.post("/chat", json={"message": "I'm taking Calc II this semester."}, headers=HEADERS)
    events = parse_sse(response.text)
    suggestions = [data for name, data in events if name == "memory_suggestion"]
    assert suggestions == [{"suggestion_id": "s1", "text": note}]
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM tool_steps").fetchone()[0] == 0


def test_a_rejected_proposal_sends_no_suggestion(client: TestClient):
    fake = app.dependency_overrides[get_provider]()
    fake.script = [ToolStep("s1", "propose_memory", "error", {"text": "x"}, {"text": "limit reached"}, "tool_error")]
    events = parse_sse(client.post("/chat", json={"message": "Hi"}, headers=HEADERS).text)
    assert [name for name, _ in events if name == "memory_suggestion"] == []


def test_tools_off_still_declares_the_client_tool_but_disables_it(client: TestClient):
    """tool_choice none is what stops a proposal; the definition stays so the cache holds."""
    fake = app.dependency_overrides[get_provider]()
    client.post("/chat", json={"message": "Hi", "tools": False}, headers=HEADERS)
    tools = fake.calls[0].opts["tools"]
    assert tools.enabled is False
    assert [tool.name for tool in tools.client_tools] == ["propose_memory"]


def test_server_wide_tools_off_offers_no_client_tool(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from api.config import settings

    monkeypatch.setattr(settings, "tools_enabled", False)
    fake = app.dependency_overrides[get_provider]()
    client.post("/chat", json={"message": "Hi"}, headers=HEADERS)
    assert fake.calls[0].opts["tools"] is None
