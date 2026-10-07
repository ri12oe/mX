"""Heartbeats and fail-fast for long model thinking (design.md §5)."""
import asyncio
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import chat as chat_module
from api import db
from api.main import app, get_db, get_provider
from api.prompts import SystemPrompt
from providers.base import ModelResponse
from providers.errors import ProviderUnavailableError
from tests.conftest import TEST_API_KEY
from tests.test_chat import count, parse_sse

HEADERS = {"X-mX-Key": TEST_API_KEY}


class SlowProvider:
    """Thinks for `delay` seconds before its first chunk, then replies (or fails)."""

    name = "slow"

    def __init__(self, delay: float, error: Exception | None = None) -> None:
        self.delay, self.error = delay, error

    async def generate(self, messages: Any, system: str, **opts: Any) -> Any:
        raise NotImplementedError

    async def stream(self, messages: Any, system: str, **opts: Any):
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        yield "Done thinking."
        yield ModelResponse(text="Done thinking.", model="claude-opus-5-5", input_tokens=10, output_tokens=3)


@pytest.fixture(autouse=True)
def fast_timers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_module, "FIRST_ITEM_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(chat_module, "HEARTBEAT_SECONDS", 0.05)


def post(conn: sqlite3.Connection, provider: Any):
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        return TestClient(app).post("/chat", json={"message": "Hard question"}, headers=HEADERS)
    finally:
        app.dependency_overrides.clear()


def test_slow_thinking_streams_heartbeats_then_the_reply(conn: sqlite3.Connection):
    r = post(conn, SlowProvider(delay=0.4))
    assert r.status_code == 200
    assert r.text.count(": ping\n\n") >= 2
    assert r.text.index("event: meta") < r.text.index(": ping")  # stream starts before the answer
    assert [name for name, _ in parse_sse(r.text)] == ["meta", "delta", "done"]
    assert count(conn, "messages") == 2


def test_fast_failure_is_still_an_http_error(conn: sqlite3.Connection):
    r = post(conn, SlowProvider(delay=0, error=ProviderUnavailableError("down")))
    assert r.status_code == 503


def test_failure_after_the_wait_becomes_an_error_event(conn: sqlite3.Connection):
    r = post(conn, SlowProvider(delay=0.3, error=ProviderUnavailableError("overloaded")))
    assert r.status_code == 200
    events = parse_sse(r.text)
    assert events[-1] == ("error", {"code": "provider_unavailable", "message": "overloaded"})
    assert count(conn, "messages") == 0


def disconnect_mid_think(conn: sqlite3.Connection, started_request: bool) -> asyncio.Event:
    """Stream until the first heartbeat, then disconnect like a browser leaving. Returns `closed`.

    With `started_request`, the fake model has begun a request (the meter holds
    its input side) before it goes quiet, like a real long think.
    """
    closed = asyncio.Event()
    pending = chat_module.PendingTurn("c", "u", "a", "q", db.now_iso(), (), [], "normal", 0.0)

    async def never_answers():
        try:
            if started_request:
                pending.meter.requests, pending.meter.model = 1, "claude-opus-5-5"
                pending.meter.input_tokens, pending.meter.cache_read_tokens = 900, 4000
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()

    async def scenario() -> None:
        stream = never_answers()
        next_item = asyncio.ensure_future(anext(stream))
        turn = chat_module.TurnContext(pending, SystemPrompt("x", "mx_system_v3"), "anthropic", conn)
        events = chat_module.stream_events(stream, next_item, turn)
        assert (await anext(events)).startswith("event: meta")
        assert await anext(events) == chat_module.HEARTBEAT
        await events.aclose()  # what the server does when the client disconnects
        assert next_item.cancelled()

    asyncio.run(scenario())
    return closed


def test_disconnect_while_thinking_cancels_the_model_call(conn: sqlite3.Connection):
    """If the browser leaves mid-think, the pending model call is cancelled and closed."""
    assert disconnect_mid_think(conn, started_request=False).is_set()
    assert count(conn, "usage") == 0  # no request had started: nothing was spent


def test_disconnect_after_spending_saves_an_aborted_usage_row(conn: sqlite3.Connection):
    """Design §5: a stopped turn saves no content, but its spend still counts toward the budget."""
    assert disconnect_mid_think(conn, started_request=True).is_set()
    row = conn.execute("SELECT * FROM usage").fetchone()
    assert (row["status"], row["message_id"], row["mode"]) == ("aborted", None, "normal")
    assert (row["input_tokens"], row["cache_read_tokens"], row["output_tokens"]) == (900, 4000, 0)
    assert row["cost_usd"] == pytest.approx((900 * 4 + 4000 * 0.20) / 1e6)
    assert count(conn, "messages") == 0 and count(conn, "conversations") == 0
