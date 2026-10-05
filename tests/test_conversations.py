"""GET/DELETE /conversations (design.md §5)."""
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api import db
from api.main import app, get_db, get_provider
from tests.conftest import TEST_API_KEY
from tests.fakes import FakeProvider

HEADERS = {"X-mX-Key": TEST_API_KEY}
T = "2026-10-01T{:02d}:00:00.000000+00:00"


@pytest.fixture
def client(conn: sqlite3.Connection) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_provider] = lambda: FakeProvider()
    yield TestClient(app)
    app.dependency_overrides.clear()


def seed(conn: sqlite3.Connection, conversation_id: str, question: str, hour: int) -> db.Turn:
    turn = db.Turn(
        conversation_id=conversation_id,
        user_message_id=db.new_id(), user_content=question, user_created_at=T.format(hour),
        assistant_message_id=db.new_id(), assistant_content=f"answer to {question}",
        usage=db.UsageRecord("fake", "fake-model", "mx_system_v1", 10, 5, None, 100),
    )
    db.save_turn(conn, turn, now=T.format(hour))
    return turn


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- Auth --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/conversations"), ("GET", "/conversations/c1"), ("DELETE", "/conversations/c1")],
)
def test_all_routes_require_key(client: TestClient, method: str, path: str):
    assert client.request(method, path).status_code == 401


# --- List --------------------------------------------------------------------


def test_list_empty(client: TestClient):
    r = client.get("/conversations", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == []


def test_list_newest_first_with_summary_fields(client: TestClient, conn: sqlite3.Connection):
    seed(conn, "old", "First question", hour=1)
    seed(conn, "new", "Second question", hour=5)

    body = client.get("/conversations", headers=HEADERS).json()
    assert [c["id"] for c in body] == ["new", "old"]
    assert body[0] == {
        "id": "new", "title": "Second question",
        "created_at": T.format(5), "updated_at": T.format(5),
    }


def test_list_limit(client: TestClient, conn: sqlite3.Connection):
    for hour in range(3):
        seed(conn, f"c{hour}", f"q{hour}", hour=hour)
    body = client.get("/conversations?limit=2", headers=HEADERS).json()
    assert [c["id"] for c in body] == ["c2", "c1"]


@pytest.mark.parametrize("limit", ["0", "-1", "201", "abc"])
def test_list_rejects_bad_limit(client: TestClient, limit: str):
    assert client.get(f"/conversations?limit={limit}", headers=HEADERS).status_code == 422


# --- Get ---------------------------------------------------------------------


def test_get_returns_messages_oldest_first(client: TestClient, conn: sqlite3.Connection):
    first = seed(conn, "c1", "What is 2 + 2?", hour=1)
    seed(conn, "c1", "And times 3?", hour=2)

    r = client.get("/conversations/c1", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert (body["id"], body["title"]) == ("c1", "What is 2 + 2?")
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("user", "What is 2 + 2?"), ("assistant", "answer to What is 2 + 2?"),
        ("user", "And times 3?"), ("assistant", "answer to And times 3?"),
    ]
    assert body["messages"][0]["id"] == first.user_message_id
    assert body["messages"][0]["image_refs"] == []


def test_get_unknown_is_404(client: TestClient):
    assert client.get("/conversations/nope", headers=HEADERS).status_code == 404


# --- Delete ------------------------------------------------------------------


def test_delete_removes_conversation_and_its_rows(client: TestClient, conn: sqlite3.Connection):
    seed(conn, "c1", "delete me", hour=1)
    seed(conn, "keep", "keep me", hour=2)

    r = client.delete("/conversations/c1", headers=HEADERS)
    assert r.status_code == 204
    assert r.content == b""

    assert client.get("/conversations/c1", headers=HEADERS).status_code == 404
    assert [c["id"] for c in client.get("/conversations", headers=HEADERS).json()] == ["keep"]
    assert count(conn, "messages") == 2  # only "keep" remains
    # Usage rows outlive the chat, unlinked, so the month's spend can't drop (design.md §16).
    assert count(conn, "usage") == 2
    assert conn.execute("SELECT COUNT(*) FROM usage WHERE message_id IS NULL").fetchone()[0] == 1


def test_delete_unknown_is_404(client: TestClient):
    assert client.delete("/conversations/nope", headers=HEADERS).status_code == 404


def test_delete_twice_is_404_the_second_time(client: TestClient, conn: sqlite3.Connection):
    seed(conn, "c1", "q", hour=1)
    assert client.delete("/conversations/c1", headers=HEADERS).status_code == 204
    assert client.delete("/conversations/c1", headers=HEADERS).status_code == 404


# --- Together with /chat -----------------------------------------------------


def test_chat_then_list_get_delete(client: TestClient):
    r = client.post("/chat", json={"message": "Hello mX"}, headers=HEADERS)
    conversation_id = r.text.split('"conversation_id": "')[1].split('"')[0]

    listed = client.get("/conversations", headers=HEADERS).json()
    assert [(c["id"], c["title"]) for c in listed] == [(conversation_id, "Hello mX")]

    detail = client.get(f"/conversations/{conversation_id}", headers=HEADERS).json()
    assert [m["content"] for m in detail["messages"]] == ["Hello mX", "Hello, Rio."]

    assert client.delete(f"/conversations/{conversation_id}", headers=HEADERS).status_code == 204
    assert client.get("/conversations", headers=HEADERS).json() == []
