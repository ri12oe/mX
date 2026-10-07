"""Tool steps and citations: migration 0003, atomic save, clipping, API (design.md §5, §7)."""
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import db
from api.main import app, get_db
from api.migrate import MIGRATIONS_DIR, TARGET_VERSION, migrate
from tests.test_chat import HEADERS

T0 = "2026-10-08T10:00:00.000000+00:00"
T1 = "2026-10-08T10:00:09.000000+00:00"

CODE_STEP = db.NewToolStep("s1", "code_execution", "ok", {"code": "print(2**100)"},
                           {"stdout": "1267650600228229401496703205376\n", "stderr": "", "return_code": 0})
SEARCH_STEP = db.NewToolStep("s2", "web_search", "ok", {"query": "Python 3.14 release date"},
                             {"sources": [{"url": "https://www.python.org/downloads/", "title": "Python downloads"}]})
FAILED_STEP = db.NewToolStep("s3", "web_search", "error", {"query": "x"}, None, "unavailable")
CITATION = db.Citation("https://www.python.org/downloads/", "Python downloads")


def turn(steps: tuple[db.NewToolStep, ...] = (CODE_STEP, SEARCH_STEP),
         citations: tuple[db.Citation, ...] = (CITATION,)) -> db.Turn:
    usage = db.UsageRecord("anthropic", "claude-opus-5-5", "v", 10, 5, 0.01, 100, code_runs=1, web_searches=1)
    return db.Turn("c1", "u1", "Compute 2^100 and check Python's release", T0, "a1",
                   "2^100 = 1267650600228229401496703205376.", usage, tool_steps=steps, citations=citations)


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- Migration 0003 ----------------------------------------------------------


def v2_database(path: Path) -> None:
    """A database at schema v2 (before tool steps) with one saved turn, written as v2 code wrote it."""
    directory = path.parent / "v2-only"
    directory.mkdir()
    for name in ("0001_initial.sql", "0002_usage_v2.sql"):
        shutil.copy(MIGRATIONS_DIR / name, directory)
    migrate(path, directory)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("INSERT INTO conversations VALUES ('c1', 'Hello', ?, ?)", (T0, T0))
        conn.execute("INSERT INTO messages VALUES ('u1', 'c1', 'user', 'Hello', '[]', ?)", (T0,))
        conn.execute("INSERT INTO messages VALUES ('a1', 'c1', 'assistant', 'Hi', '[]', ?)", (T0,))
        conn.execute("INSERT INTO usage (id, message_id, provider, model, prompt_version, input_tokens,"
                     " output_tokens, latency_ms, created_at) VALUES ('g1', 'a1', 'p', 'm', 'v', 1, 1, 1, ?)", (T0,))
    conn.close()


def test_v2_to_v3_keeps_every_row(tmp_path: Path):
    path = tmp_path / "mx.db"
    v2_database(path)
    backup = migrate(path, now=datetime(2026, 10, 8, tzinfo=timezone.utc))

    assert TARGET_VERSION >= 3
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == TARGET_VERSION
    assert [count(conn, t) for t in ("conversations", "messages", "usage", "tool_steps")] == [1, 2, 1, 0]
    convo = db.get_conversation(conn, "c1")
    assert convo is not None
    assert [(m["content"], m["citations"], m["tool_steps"]) for m in convo["messages"]] == [
        ("Hello", [], []), ("Hi", [], [])]
    conn.close()
    assert backup is not None and sqlite3.connect(backup).execute("PRAGMA user_version").fetchone()[0] == 2


# --- Saving ------------------------------------------------------------------


def test_steps_and_citations_are_saved_with_the_turn(conn: sqlite3.Connection):
    db.save_turn(conn, turn(), now=T1)
    convo = db.get_conversation(conn, "c1")
    assert convo is not None
    user, assistant = convo["messages"]
    assert (user["tool_steps"], user["citations"]) == ([], [])
    assert assistant["citations"] == [{"url": "https://www.python.org/downloads/", "title": "Python downloads"}]
    steps = assistant["tool_steps"]
    assert [(s["seq"], s["id"], s["tool"], s["status"]) for s in steps] == [
        (0, "s1", "code_execution", "ok"), (1, "s2", "web_search", "ok")]
    assert steps[0]["input"] == {"code": "print(2**100)"}
    assert steps[0]["output"]["return_code"] == 0
    assert steps[1]["output"]["sources"][0]["title"] == "Python downloads"


def test_a_failed_step_is_stored_with_its_error_code(conn: sqlite3.Connection):
    db.save_turn(conn, turn(steps=(FAILED_STEP,), citations=()), now=T1)
    step = db.get_conversation(conn, "c1")["messages"][1]["tool_steps"][0]  # type: ignore[index]
    assert (step["status"], step["output"], step["error_code"]) == ("error", None, "unavailable")


def test_a_failing_step_insert_rolls_back_the_whole_turn(conn: sqlite3.Connection):
    """Design §5: content is atomic. A duplicate step id fails the insert; nothing is kept."""
    duplicate = db.NewToolStep("s1", "web_search", "ok", {"query": "again"})
    with pytest.raises(sqlite3.IntegrityError):
        db.save_turn(conn, turn(steps=(CODE_STEP, duplicate)))
    for table in ("conversations", "messages", "tool_steps", "usage"):
        assert count(conn, table) == 0


def test_deleting_the_conversation_deletes_its_steps(conn: sqlite3.Connection):
    db.save_turn(conn, turn())
    assert count(conn, "tool_steps") == 2
    assert db.delete_conversation(conn, "c1")
    assert count(conn, "tool_steps") == 0
    assert count(conn, "usage") == 1  # spend is kept (design.md §16)


# --- Clipping ----------------------------------------------------------------


def test_code_and_outputs_are_clipped_and_flagged():
    step = db.NewToolStep("s", "code_execution", "ok", {"code": "x" * 8_001},
                          {"stdout": "o" * 4_001, "stderr": "e" * 10, "return_code": 1, "files": ["big.bin"]})
    clipped = db.clip_step(step)
    assert len(clipped.input["code"]) == 8_000 and clipped.input["code_truncated"] is True
    assert clipped.output is not None
    assert len(clipped.output["stdout"]) == 4_000 and clipped.output["stdout_truncated"] is True
    assert clipped.output["stderr"] == "e" * 10 and "stderr_truncated" not in clipped.output
    assert clipped.output["return_code"] == 1
    assert "files" not in clipped.output  # only known fields are stored


def test_exact_limits_are_not_flagged():
    step = db.NewToolStep("s", "code_execution", "ok", {"code": "x" * 8_000}, {"stdout": "o" * 4_000})
    clipped = db.clip_step(step)
    assert "code_truncated" not in clipped.input
    assert clipped.output == {"stdout": "o" * 4_000}


def test_search_keeps_at_most_ten_sources_and_no_page_content():
    sources = [{"url": f"https://example.com/{i}", "title": f"Page {i}", "page_content": "lots of text",
                "encrypted_content": "abc"} for i in range(12)]
    sources.insert(0, {"title": "no url"})  # malformed entries are dropped
    clipped = db.clip_step(db.NewToolStep("s", "web_search", "ok", {"query": "q"}, {"sources": sources}))
    assert clipped.output is not None
    kept = clipped.output["sources"]
    assert len(kept) == 10
    assert kept[0] == {"url": "https://example.com/0", "title": "Page 0"}
    assert all(set(s) == {"url", "title"} for s in kept)


def test_long_citations_are_clipped(conn: sqlite3.Connection):
    long = db.Citation("https://example.com/" + "a" * 3_000, "T" * 500)
    db.save_turn(conn, turn(steps=(), citations=(long,)), now=T1)
    saved = db.get_conversation(conn, "c1")["messages"][1]["citations"][0]  # type: ignore[index]
    assert len(saved["url"]) == db.MAX_URL_CHARS and len(saved["title"]) == db.MAX_TITLE_CHARS


# --- API ---------------------------------------------------------------------


def test_get_conversation_returns_steps_and_citations(conn: sqlite3.Connection):
    db.save_turn(conn, turn(), now=T1)
    app.dependency_overrides[get_db] = lambda: conn
    try:
        body = TestClient(app).get("/conversations/c1", headers=HEADERS).json()
    finally:
        app.dependency_overrides.clear()
    user, assistant = body["messages"]
    assert (user["tool_steps"], user["citations"]) == ([], [])
    assert [s["tool"] for s in assistant["tool_steps"]] == ["code_execution", "web_search"]
    assert assistant["tool_steps"][0]["output"]["stdout"].startswith("126765")
    assert assistant["citations"] == [{"url": "https://www.python.org/downloads/", "title": "Python downloads"}]
