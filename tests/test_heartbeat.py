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


def test_disconnect_while_thinking_cancels_the_model_call():
    """If the browser leaves mid-think, the pending model call is cancelled and closed."""
    closed = asyncio.Event()

    async def never_answers():
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            closed.set()

    async def scenario() -> None:
        stream = never_answers()
        pending = chat_module.PendingTurn("c", "u", "a", "q", db.now_iso(), (), [], 0.0)
        next_item = asyncio.ensure_future(anext(stream))
        events = chat_module.stream_events(stream, next_item, pending, None, "p", None)  # type: ignore[arg-type]
        assert (await anext(events)).startswith("event: meta")
        assert await anext(events) == chat_module.HEARTBEAT
        await events.aclose()  # what the server does when the client disconnects
        assert next_item.cancelled()
        assert closed.is_set()

    asyncio.run(scenario())
