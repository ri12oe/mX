"""POST /chat with the FakeProvider (design.md §5, §6). No network, no cost."""
import json
import logging
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import chat as chat_module
from api import db
from api.config import settings
from api.main import app, get_db, get_provider
from providers.errors import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderUnavailableError,
)
from tests.conftest import TEST_API_KEY
from tests.fakes import FakeProvider

HEADERS = {"X-mX-Key": TEST_API_KEY}
T = "2026-10-01T10:00:{:02d}.000000+00:00"


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider(chunks=["The answer ", "is 12."], model="claude-opus-5-5",
                        input_tokens=500, output_tokens=40)


@pytest.fixture
def client(conn: sqlite3.Connection, fake: FakeProvider) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_provider] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


def post_chat(client: TestClient, **body: Any):
    return client.post("/chat", json={"message": "What is 4 times 3?", **body}, headers=HEADERS)


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def seed_turns(conn: sqlite3.Connection, conversation_id: str, n: int) -> None:
    for i in range(n):
        db.save_turn(conn, db.Turn(
            conversation_id=conversation_id,
            user_message_id=db.new_id(), user_content=f"q{i}", user_created_at=T.format(2 * i),
            assistant_message_id=db.new_id(), assistant_content=f"a{i}",
            usage=db.UsageRecord("fake", "fake-model", "v", 1, 1, None, 1),
        ), now=T.format(2 * i + 1))


# --- Happy path --------------------------------------------------------------


def test_requires_key(client: TestClient):
    assert client.post("/chat", json={"message": "hi"}).status_code == 401


def test_new_conversation_streams_meta_deltas_done(client: TestClient):
    r = post_chat(client)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(r.text)
    assert [name for name, _ in events] == ["meta", "delta", "delta", "done"]
    assert "".join(data["text"] for name, data in events if name == "delta") == "The answer is 12."

    done = events[-1][1]
    assert done["usage"] == {
        "model": "claude-opus-5-5", "input_tokens": 500, "output_tokens": 40,
        "cost_usd": pytest.approx(0.0028),  # 500 × $4/M + 40 × $20/M
    }
    assert done["stop_reason"] == "end_turn"


def test_turn_is_saved_with_usage(client: TestClient, conn: sqlite3.Connection):
    meta = parse_sse(post_chat(client).text)[0][1]

    convo = db.get_conversation(conn, meta["conversation_id"])
    assert convo is not None
    assert convo["title"] == "What is 4 times 3?"
    assert [(m["role"], m["content"]) for m in convo["messages"]] == [
        ("user", "What is 4 times 3?"), ("assistant", "The answer is 12."),
    ]
    assert convo["messages"][1]["id"] == meta["message_id"]

    usage = conn.execute("SELECT * FROM usage").fetchone()
    assert usage["message_id"] == meta["message_id"]
    assert (usage["provider"], usage["model"], usage["prompt_version"]) == ("fake", "claude-opus-5-5", "mx_system_v3")
    assert (usage["input_tokens"], usage["output_tokens"]) == (500, 40)
    assert usage["cost_usd"] == pytest.approx(0.0028)
    assert usage["latency_ms"] >= 0


def test_provider_gets_system_prompt_and_normal_mode_options(client: TestClient, fake: FakeProvider):
    post_chat(client)
    call = fake.calls[0]
    assert call.method == "stream"
    assert call.system.startswith("You are mX") and "Mode: normal" in call.system
    assert "<!--" not in call.system
    assert call.opts == {"max_tokens": 16000, "effort": "high"}
    assert [(m.role, m.content) for m in call.messages] == [("user", "What is 4 times 3?")]


def test_brief_mode_uses_brief_prompt_and_options(client: TestClient, fake: FakeProvider):
    post_chat(client, mode="brief")
    call = fake.calls[0]
    assert "Mode: brief" in call.system
    assert call.opts == {"max_tokens": 2048, "effort": "low"}


def test_follow_up_sends_history_and_appends(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    conversation_id = parse_sse(post_chat(client).text)[0][1]["conversation_id"]
    r = post_chat(client, conversation_id=conversation_id, message="And plus 1?")
    assert r.status_code == 200

    history = [(m.role, m.content) for m in fake.calls[1].messages]
    assert history == [
        ("user", "What is 4 times 3?"), ("assistant", "The answer is 12."), ("user", "And plus 1?"),
    ]
    convo = db.get_conversation(conn, conversation_id)
    assert convo is not None and len(convo["messages"]) == 4


def test_unknown_price_saves_null_cost(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    fake.model = "claude-mystery-9"
    done = parse_sse(post_chat(client).text)[-1][1]
    assert done["usage"]["cost_usd"] is None
    assert conn.execute("SELECT cost_usd FROM usage").fetchone()[0] is None


def test_truncated_reply_is_saved_and_reported(client: TestClient, fake: FakeProvider, monkeypatch: pytest.MonkeyPatch):
    original = fake._response

    def truncated():
        r = original()
        r.stop_reason = "max_tokens"
        return r

    monkeypatch.setattr(fake, "_response", truncated)
    assert parse_sse(post_chat(client).text)[-1][1]["stop_reason"] == "max_tokens"


def test_works_with_the_real_db_dependency(fake: FakeProvider):
    """The stream saves after the route returns; get_db's connection must still be open."""
    app.dependency_overrides[get_provider] = lambda: fake
    try:
        with TestClient(app) as real_client:  # lifespan creates the test database
            r = post_chat(real_client)
    finally:
        app.dependency_overrides.clear()
    conversation_id = parse_sse(r.text)[0][1]["conversation_id"]
    check = db.connect(settings.db_path)
    assert db.conversation_exists(check, conversation_id)
    check.close()


# --- History window ----------------------------------------------------------


def test_history_window_is_capped_and_starts_with_user(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    seed_turns(conn, "c1", 15)  # 30 stored messages
    post_chat(client, conversation_id="c1", message="latest")

    sent = fake.calls[0].messages
    assert len(sent) <= chat_module.HISTORY_WINDOW
    assert sent[0].role == "user"
    assert (sent[-1].role, sent[-1].content) == ("user", "latest")
    assert (sent[-2].role, sent[-2].content) == ("assistant", "a14")  # most recent history kept


def test_build_history_drops_leading_assistant_messages():
    stored = [{"role": "assistant", "content": "a0", "image_refs": []},
              {"role": "user", "content": "q1", "image_refs": []},
              {"role": "assistant", "content": "a1", "image_refs": []}]
    history = chat_module.build_history(stored, "q2")
    assert [(m.role, m.content) for m in history] == [("user", "q1"), ("assistant", "a1"), ("user", "q2")]


# --- Validation (before streaming) -------------------------------------------


def test_unknown_conversation_is_404_and_provider_not_called(client: TestClient, fake: FakeProvider):
    assert post_chat(client, conversation_id="does-not-exist").status_code == 404
    assert fake.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": "   \n "},
        {"message": "x" * (chat_module.MAX_MESSAGE_CHARS + 1)},
        {"message": "hi", "mode": "loud"},
        {"message": "hi", "images": ["aGk="]},
        {},
    ],
)
def test_invalid_requests_are_422(client: TestClient, fake: FakeProvider, body: dict[str, Any]):
    assert client.post("/chat", json=body, headers=HEADERS).status_code == 422
    assert fake.calls == []


def test_oversized_body_is_413(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(chat_module, "MAX_BODY_BYTES", 10)
    assert post_chat(client).status_code == 413


# --- Provider failures before any text: HTTP errors, nothing saved -----------


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProviderUnavailableError("down"), 503, "provider_unavailable"),
        (ProviderRateLimitError("slow"), 503, "provider_rate_limited"),
        (ProviderAuthError("bad key"), 502, "provider_auth"),
        (ProviderRefusalError("no", category="cyber"), 422, "provider_refused"),
    ],
)
def test_failure_before_text_is_http_error(
    client: TestClient, conn: sqlite3.Connection, fake: FakeProvider,
    error: Exception, status: int, code: str,
):
    fake.error = error  # raised before any chunk
    r = post_chat(client)
    assert r.status_code == status
    assert r.json()["detail"]["code"] == code
    assert count(conn, "conversations") == count(conn, "messages") == 0


# --- Failures after streaming started: error event, nothing saved ------------


def test_mid_stream_failure_sends_error_event_and_saves_nothing(
    client: TestClient, conn: sqlite3.Connection, fake: FakeProvider,
):
    fake.chunks = ["a", "b", "c"]
    fake.error, fake.fail_after = ProviderUnavailableError("connection lost"), 2
    r = post_chat(client)

    assert r.status_code == 200
    events = parse_sse(r.text)
    assert [name for name, _ in events] == ["meta", "delta", "delta", "error"]
    assert events[-1][1]["code"] == "provider_unavailable"
    for table in ("conversations", "messages", "usage"):
        assert count(conn, table) == 0


def test_unrescued_refusal_mid_stream_is_discarded(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    fake.chunks = ["Sure, ", "here is", " more"]
    fake.error, fake.fail_after = ProviderRefusalError("declined", category="bio"), 2
    events = parse_sse(post_chat(client).text)
    assert events[-1] == ("error", {"code": "provider_refused", "message": "declined"})
    assert count(conn, "messages") == 0


def test_save_failure_sends_error_event(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def broken_save(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(db, "save_turn", broken_save)
    events = parse_sse(post_chat(client).text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "save_failed"


# --- Logging -----------------------------------------------------------------


def test_logs_one_line_without_message_content(client: TestClient, caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO, logger="mx.chat"):
        meta = parse_sse(post_chat(client, message="my secret homework").text)[0][1]

    lines = [r.getMessage() for r in caplog.records if r.name == "mx.chat"]
    assert len(lines) == 1
    assert meta["conversation_id"] in lines[0] and "status=ok" in lines[0]
    assert "cost_usd=0.0028" in lines[0]
    assert "secret homework" not in caplog.text
    assert "The answer" not in caplog.text


def test_failed_turn_is_logged_as_warning(client: TestClient, fake: FakeProvider, caplog: pytest.LogCaptureFixture):
    fake.error = ProviderUnavailableError("down")
    with caplog.at_level(logging.INFO, logger="mx.chat"):
        post_chat(client)
    record = next(r for r in caplog.records if r.name == "mx.chat")
    assert record.levelno == logging.WARNING and "status=provider_unavailable" in record.getMessage()
