"""Memories: migration 0004, repository limits, and the /memories API (design.md §7, §18)."""
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import db
from api.main import app, get_db
from api.migrate import MIGRATIONS_DIR, TARGET_VERSION, migrate
from tests.conftest import TEST_API_KEY

HEADERS = {"X-mX-Key": TEST_API_KEY}
T0 = "2026-10-08T10:00:00.000000+00:00"


def test_v3_to_v4_keeps_every_row(tmp_path: Path):
    path = tmp_path / "mx.db"
    directory = tmp_path / "v3-only"
    directory.mkdir()
    for name in ("0001_initial.sql", "0002_usage_v2.sql", "0003_tool_steps.sql"):
        shutil.copy(MIGRATIONS_DIR / name, directory)
    migrate(path, directory)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("INSERT INTO conversations VALUES ('c1', 'Hello', ?, ?)", (T0, T0))
        conn.execute("INSERT INTO messages VALUES ('u1', 'c1', 'user', 'Hello', '[]', ?, '[]')", (T0,))
    conn.close()

    backup = migrate(path, now=datetime(2026, 10, 20, tzinfo=timezone.utc))
    opened = db.connect(path)
    assert TARGET_VERSION >= 4
    assert opened.execute("PRAGMA user_version").fetchone()[0] == TARGET_VERSION
    assert opened.execute("SELECT title FROM conversations").fetchone()[0] == "Hello"
    assert db.list_memories(opened) == []
    opened.close()
    assert backup is not None
    assert sqlite3.connect(backup).execute("PRAGMA user_version").fetchone()[0] == 3


def test_repository_enforces_length_count_and_duplicates(conn: sqlite3.Connection):
    saved = db.add_memory(conn, "  Rio is taking Calc II.  ", now=T0)
    assert saved["text"] == "Rio is taking Calc II."
    assert [row["text"] for row in db.list_memories(conn)] == ["Rio is taking Calc II."]

    with pytest.raises(db.MemoryRejected, match="blank"):
        db.add_memory(conn, "   ")
    with pytest.raises(db.MemoryRejected, match="too_long"):
        db.add_memory(conn, "x" * 201)
    with pytest.raises(db.MemoryRejected, match="memory_duplicate"):
        db.add_memory(conn, "rio is taking calc ii.")
    assert db.count_memories(conn) == 1

    updated = db.update_memory(conn, saved["id"], "Rio prefers Python.", now=T0)
    assert updated is not None and updated["text"] == "Rio prefers Python."
    assert db.update_memory(conn, "missing", "nope") is None
    assert db.delete_memory(conn, saved["id"]) is True
    assert db.delete_memory(conn, saved["id"]) is False


def test_repository_stops_at_fifty(conn: sqlite3.Connection):
    for i in range(db.MEMORY_LIMIT):
        db.add_memory(conn, f"note {i}", now=T0)
    with pytest.raises(db.MemoryRejected, match="memory_limit"):
        db.add_memory(conn, "one more", now=T0)
    assert db.count_memories(conn) == db.MEMORY_LIMIT


@pytest.fixture
def client(conn: sqlite3.Connection) -> TestClient:
    app.dependency_overrides[get_db] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_memories_api(client: TestClient, conn: sqlite3.Connection):
    assert client.get("/memories").status_code == 401
    assert client.get("/memories", headers=HEADERS).json() == []

    created = client.post("/memories", json={"text": " Rio prefers Python. ", "source_conversation_id": "c1"}, headers=HEADERS)
    assert created.status_code == 201
    body = created.json()
    assert body["text"] == "Rio prefers Python." and body["source_conversation_id"] == "c1"

    assert client.post("/memories", json={"text": "   "}, headers=HEADERS).status_code == 422
    assert client.post("/memories", json={"text": "x" * 201}, headers=HEADERS).status_code == 422
    duplicate = client.post("/memories", json={"text": "rio prefers python."}, headers=HEADERS)
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "memory_duplicate"

    patched = client.patch(f"/memories/{body['id']}", json={"text": "Rio prefers Python and types."}, headers=HEADERS)
    assert patched.status_code == 200 and patched.json()["text"].endswith("types.")
    assert client.patch("/memories/missing", json={"text": "nope"}, headers=HEADERS).status_code == 404

    assert client.delete(f"/memories/{body['id']}", headers=HEADERS).status_code == 204
    assert client.delete(f"/memories/{body['id']}", headers=HEADERS).status_code == 404
    assert db.count_memories(conn) == 0


def test_memory_limit_is_409(client: TestClient, conn: sqlite3.Connection):
    for i in range(db.MEMORY_LIMIT):
        db.add_memory(conn, f"note {i}", now=T0)
    limited = client.post("/memories", json={"text": "one more"}, headers=HEADERS)
    assert limited.status_code == 409 and limited.json()["detail"]["code"] == "memory_limit"
