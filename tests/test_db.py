import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import db
from api.config import settings
from api.main import app, get_db

T0 = "2026-10-01T10:00:00.000000+00:00"
T1 = "2026-10-01T10:00:05.000000+00:00"
T2 = "2026-10-01T11:00:00.000000+00:00"
T3 = "2026-10-01T11:00:05.000000+00:00"


def make_usage(**overrides: object) -> db.UsageRecord:
    values: dict[str, object] = dict(
        provider="anthropic", model="claude-sonnet-5-5", prompt_version="mx_system_v1",
        input_tokens=120, output_tokens=45, cost_usd=0.001, latency_ms=850,
    )
    values.update(overrides)
    return db.UsageRecord(**values)  # type: ignore[arg-type]


def make_turn(conversation_id: str, user: str = "Hello", reply: str = "Hi", at: str = T0) -> db.Turn:
    return db.Turn(
        conversation_id=conversation_id,
        user_message_id=db.new_id(), user_content=user, user_created_at=at,
        assistant_message_id=db.new_id(), assistant_content=reply,
        usage=make_usage(),
    )


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- Setup -----------------------------------------------------------------


def test_init_creates_all_tables(conn: sqlite3.Connection):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"conversations", "messages", "images", "usage"} <= names


def test_init_sets_version_wal_and_foreign_keys(conn: sqlite3.Connection):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_init_is_safe_to_run_twice_and_keeps_data(tmp_path: Path):
    path = tmp_path / "twice.db"
    db.init_db(path)
    c = db.connect(path)
    db.save_turn(c, make_turn("c1"))
    c.close()
    db.init_db(path)
    c = db.connect(path)
    assert db.conversation_exists(c, "c1")
    c.close()


def test_init_creates_missing_parent_folder(tmp_path: Path):
    path = tmp_path / "nested" / "data" / "mx.db"
    db.init_db(path)
    assert path.is_file()


def test_init_refuses_newer_schema(tmp_path: Path):
    path = tmp_path / "future.db"
    c = sqlite3.connect(path)
    c.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    c.close()
    with pytest.raises(db.SchemaVersionError):
        db.init_db(path)


# --- Titles ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "title"),
    [
        ("What is 2 + 2?", "What is 2 + 2?"),
        ("x" * 100, "x" * 60),
        ("line one\n\n  line   two", "line one line two"),
        ("   \n  ", db.DEFAULT_TITLE),
    ],
)
def test_make_title(message: str, title: str):
    assert db.make_title(message) == title


# --- save_turn -------------------------------------------------------------


def test_save_turn_creates_conversation_messages_and_usage(conn: sqlite3.Connection):
    turn = make_turn("c1", user="Explain recursion", reply="Recursion is...")
    db.save_turn(conn, turn, now=T1)

    convo = db.get_conversation(conn, "c1")
    assert convo is not None
    assert convo["title"] == "Explain recursion"
    assert (convo["created_at"], convo["updated_at"]) == (T0, T1)
    assert [(m["role"], m["content"]) for m in convo["messages"]] == [
        ("user", "Explain recursion"), ("assistant", "Recursion is..."),
    ]
    assert convo["messages"][0]["image_refs"] == []

    usage = conn.execute("SELECT * FROM usage").fetchone()
    assert usage["message_id"] == turn.assistant_message_id
    assert usage["prompt_version"] == "mx_system_v1"
    assert (usage["input_tokens"], usage["output_tokens"]) == (120, 45)


def test_second_turn_keeps_title_and_bumps_updated_at(conn: sqlite3.Connection):
    db.save_turn(conn, make_turn("c1", user="First question", at=T0), now=T1)
    db.save_turn(conn, make_turn("c1", user="Follow-up", at=T2), now=T3)

    convo = db.get_conversation(conn, "c1")
    assert convo is not None
    assert convo["title"] == "First question"
    assert (convo["created_at"], convo["updated_at"]) == (T0, T3)
    assert len(convo["messages"]) == 4


def test_save_turn_allows_unknown_cost(conn: sqlite3.Connection):
    turn = db.Turn(**{**make_turn("c1").__dict__, "usage": make_usage(cost_usd=None)})
    db.save_turn(conn, turn)
    assert conn.execute("SELECT cost_usd FROM usage").fetchone()[0] is None


def test_save_turn_is_atomic(conn: sqlite3.Connection):
    """If any insert fails, nothing from the turn is saved (design.md §5)."""
    bad = make_turn("c1")
    bad = db.Turn(**{**bad.__dict__, "assistant_message_id": bad.user_message_id})
    with pytest.raises(sqlite3.IntegrityError):
        db.save_turn(conn, bad)
    for table in ("conversations", "messages", "usage"):
        assert count(conn, table) == 0


# --- Reads -----------------------------------------------------------------


def test_list_conversations_newest_first_with_limit(conn: sqlite3.Connection):
    db.save_turn(conn, make_turn("old", at=T0), now=T1)
    db.save_turn(conn, make_turn("new", at=T2), now=T3)
    assert [c["id"] for c in db.list_conversations(conn)] == ["new", "old"]
    assert [c["id"] for c in db.list_conversations(conn, limit=1)] == ["new"]


def test_get_unknown_conversation_returns_none(conn: sqlite3.Connection):
    assert db.get_conversation(conn, "nope") is None
    assert not db.conversation_exists(conn, "nope")


def test_recent_messages_returns_last_n_oldest_first(conn: sqlite3.Connection):
    for i in range(3):
        at = f"2026-10-01T1{i}:00:00.000000+00:00"
        db.save_turn(conn, make_turn("c1", user=f"q{i}", reply=f"a{i}", at=at),
                     now=f"2026-10-01T1{i}:00:01.000000+00:00")
    recent = db.get_recent_messages(conn, "c1", limit=4)
    assert [m["content"] for m in recent] == ["q1", "a1", "q2", "a2"]


def test_messages_with_same_timestamp_keep_insert_order(conn: sqlite3.Connection):
    db.save_turn(conn, make_turn("c1", user="question", reply="answer", at=T0), now=T0)
    convo = db.get_conversation(conn, "c1")
    assert convo is not None
    assert [m["role"] for m in convo["messages"]] == ["user", "assistant"]


# --- Delete + cascade ------------------------------------------------------


def test_delete_cascades_to_messages_images_and_usage(conn: sqlite3.Connection):
    turn = make_turn("c1")
    db.save_turn(conn, turn)
    with conn:
        conn.execute(
            "INSERT INTO images (id, message_id, media_type, data, created_at)"
            " VALUES (?, ?, 'image/png', ?, ?)",
            (db.new_id(), turn.user_message_id, b"\x89PNG", T0),
        )
    db.save_turn(conn, make_turn("c2"))  # another conversation must survive

    assert db.delete_conversation(conn, "c1") is True
    assert not db.conversation_exists(conn, "c1")
    assert count(conn, "images") == 0
    assert count(conn, "messages") == 2  # only c2's turn
    assert count(conn, "usage") == 1


def test_delete_unknown_conversation_returns_false(conn: sqlite3.Connection):
    assert db.delete_conversation(conn, "nope") is False


def test_foreign_keys_reject_orphan_message(conn: sqlite3.Connection):
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, created_at)"
                " VALUES ('m1', 'missing', 'user', 'hi', ?)",
                (T0,),
            )


# --- App wiring ------------------------------------------------------------


def test_app_startup_creates_database():
    with TestClient(app):  # entering the client runs the startup (lifespan) hook
        pass
    assert Path(settings.db_path).is_file()


def test_get_db_yields_working_connection_and_closes_it():
    db.init_db(settings.db_path)
    gen = get_db()
    c = next(gen)
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    gen.close()
    with pytest.raises(sqlite3.ProgrammingError):
        c.execute("SELECT 1")
