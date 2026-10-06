"""SQLite access for mX (design.md §7).

Plain stdlib sqlite3, sync calls, no ORM. Each request gets its own
connection from the `get_db` dependency in api/main.py.
"""
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

TITLE_MAX_CHARS = 60
DEFAULT_TITLE = "New conversation"


UsageStatus = Literal["ok", "failed", "aborted"]


@dataclass(frozen=True)
class UsageRecord:
    """Token and cost numbers for one turn (schema v2, design.md §7)."""

    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: int
    mode: Literal["normal", "brief"] | None = None
    status: UsageStatus = "ok"
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    web_searches: int = 0
    code_runs: int = 0
    requests: int = 1  # API requests in the turn (tool use can need several)


@dataclass(frozen=True)
class NewImage:
    """An image attached to the user message of a turn."""

    id: str
    media_type: str
    data: bytes


@dataclass(frozen=True)
class Turn:
    """One user message plus the assistant reply, saved together."""

    conversation_id: str
    user_message_id: str
    user_content: str
    user_created_at: str
    assistant_message_id: str
    assistant_content: str
    usage: UsageRecord
    user_images: tuple[NewImage, ...] = ()


class SchemaVersionError(RuntimeError):
    """The database was created by a newer version of mX."""


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def make_title(message: str) -> str:
    """Title = first 60 characters of the first user message, whitespace collapsed."""
    title = " ".join(message.split())[:TITLE_MAX_CHARS].rstrip()
    return title or DEFAULT_TITLE


# --- Connections and setup -------------------------------------------------


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with foreign keys on and dict-like rows.

    check_same_thread=False because FastAPI may run a dependency and its
    route on different worker threads; each request still uses its own
    connection one step at a time.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Creating and upgrading the schema lives in api/migrate.py (design.md §7.1).


# --- Writes ----------------------------------------------------------------


def save_turn(conn: sqlite3.Connection, turn: Turn, now: str | None = None) -> None:
    """Save a finished turn atomically (design.md §5): all rows or none.

    Creates the conversation if it's new (titled from the user message),
    otherwise bumps its updated_at. The user message's images are stored in
    the same transaction and listed in its image_refs.
    """
    now = now or now_iso()
    with conn:  # one transaction: commit on success, roll back on any error
        conn.execute(
            """
            INSERT INTO conversations (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (turn.conversation_id, make_title(turn.user_content), turn.user_created_at, now),
        )
        _insert_message(conn, turn.user_message_id, turn.conversation_id, "user",
                        turn.user_content, turn.user_created_at,
                        image_refs=[image.id for image in turn.user_images])
        for image in turn.user_images:
            _insert_image(conn, image, turn.user_message_id, turn.user_created_at)
        _insert_message(conn, turn.assistant_message_id, turn.conversation_id, "assistant",
                        turn.assistant_content, now)
        _insert_usage(conn, turn.assistant_message_id, turn.usage, now)


def _insert_message(
    conn: sqlite3.Connection, message_id: str, conversation_id: str,
    role: str, content: str, created_at: str, image_refs: list[str] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, image_refs, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (message_id, conversation_id, role, content, json.dumps(image_refs or []), created_at),
    )


def _insert_image(
    conn: sqlite3.Connection, image: NewImage, message_id: str, created_at: str
) -> None:
    conn.execute(
        "INSERT INTO images (id, message_id, media_type, data, created_at) VALUES (?, ?, ?, ?, ?)",
        (image.id, message_id, image.media_type, image.data, created_at),
    )


def _insert_usage(
    conn: sqlite3.Connection, message_id: str | None, usage: UsageRecord, created_at: str
) -> None:
    conn.execute(
        """
        INSERT INTO usage (id, message_id, provider, model, prompt_version, mode, status,
                           input_tokens, output_tokens, cache_read_tokens,
                           cache_write_5m_tokens, cache_write_1h_tokens, web_searches,
                           code_runs, requests, cost_usd, latency_ms, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (new_id(), message_id, usage.provider, usage.model, usage.prompt_version,
         usage.mode, usage.status, usage.input_tokens, usage.output_tokens,
         usage.cache_read_tokens, usage.cache_write_5m_tokens, usage.cache_write_1h_tokens,
         usage.web_searches, usage.code_runs, usage.requests, usage.cost_usd,
         usage.latency_ms, created_at),
    )


def delete_conversation(conn: sqlite3.Connection, conversation_id: str) -> bool:
    """Delete a conversation and (via cascade) its messages and images.

    Its usage rows are kept with message_id set to NULL, so deleting chats
    never lowers the month's spend (design.md §7, §16).
    Returns False if it didn't exist.
    """
    with conn:
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return cur.rowcount > 0


# --- Reads -----------------------------------------------------------------


def conversation_exists(conn: sqlite3.Connection, conversation_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,))
    return row.fetchone() is not None


def list_conversations(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    """Newest-updated first (design.md §5)."""
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations"
        " ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def get_conversation(conn: sqlite3.Connection, conversation_id: str) -> dict[str, Any] | None:
    """The conversation with all its messages, oldest first. None if unknown."""
    row = conn.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if row is None:
        return None
    rows = conn.execute(
        "SELECT id, role, content, image_refs, created_at FROM messages"
        " WHERE conversation_id = ? ORDER BY created_at, rowid",
        (conversation_id,),
    )
    return {**dict(row), "messages": [_message_dict(r) for r in rows]}


def count_messages(conn: sqlite3.Connection, conversation_id: str) -> int:
    row = conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,))
    return row.fetchone()[0]


def get_recent_messages(
    conn: sqlite3.Connection, conversation_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    """The last `limit` messages, returned oldest first (history window, design.md §6)."""
    rows = conn.execute(
        "SELECT id, role, content, image_refs, created_at FROM messages"
        " WHERE conversation_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    return [_message_dict(r) for r in reversed(rows)]


def get_image(conn: sqlite3.Connection, image_id: str) -> tuple[str, bytes] | None:
    """(media_type, bytes) for a stored image, or None if unknown."""
    row = conn.execute("SELECT media_type, data FROM images WHERE id = ?", (image_id,)).fetchone()
    return None if row is None else (row["media_type"], row["data"])


def _message_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {**dict(row), "image_refs": json.loads(row["image_refs"])}
