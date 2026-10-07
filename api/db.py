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
class NewToolStep:
    """One tool step of the assistant reply (design.md §7, §17). Clipped when saved."""

    id: str
    tool: str  # "code_execution" | "web_search"
    status: Literal["ok", "error"]
    input: dict[str, Any]  # {"code"} | {"query"}
    output: dict[str, Any] | None = None  # {stdout, stderr, return_code} | {sources: [{url, title}]}
    error_code: str | None = None


@dataclass(frozen=True)
class Citation:
    url: str
    title: str


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
    tool_steps: tuple[NewToolStep, ...] = ()  # in order; seq = position
    citations: tuple[Citation, ...] = ()


# Stored sizes (design.md §7): enough to show what happened, never whole web pages.
MAX_CODE_CHARS = 8_000
MAX_OUTPUT_CHARS = 4_000  # each of stdout and stderr
MAX_SOURCES = 10
MAX_URL_CHARS = 2_000
MAX_TITLE_CHARS = 300


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
                        turn.assistant_content, now,
                        citations=[clip_citation(c) for c in turn.citations])
        for seq, step in enumerate(turn.tool_steps):
            _insert_tool_step(conn, turn.assistant_message_id, seq, clip_step(step), now)
        _insert_usage(conn, turn.assistant_message_id, turn.usage, now)


def save_spend(conn: sqlite3.Connection, usage: UsageRecord, now: str | None = None) -> None:
    """A usage row with no message: what a failed or stopped turn cost (design.md §5)."""
    with conn:
        _insert_usage(conn, None, usage, now or now_iso())


def _insert_message(
    conn: sqlite3.Connection, message_id: str, conversation_id: str,
    role: str, content: str, created_at: str, image_refs: list[str] | None = None,
    citations: list[dict[str, str]] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO messages (id, conversation_id, role, content, image_refs, citations, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (message_id, conversation_id, role, content, json.dumps(image_refs or []),
         json.dumps(citations or []), created_at),
    )


def _insert_tool_step(
    conn: sqlite3.Connection, message_id: str, seq: int, step: NewToolStep, created_at: str
) -> None:
    conn.execute(
        "INSERT INTO tool_steps (id, message_id, seq, tool, status, input, output, error_code, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (step.id, message_id, seq, step.tool, step.status, json.dumps(step.input),
         None if step.output is None else json.dumps(step.output), step.error_code, created_at),
    )


# --- Clipping (stored sizes, design.md §7) -----------------------------------


def clip_text(text: str, limit: int) -> tuple[str, bool]:
    """(text cut to `limit` characters, whether it was cut)."""
    return (text, False) if len(text) <= limit else (text[:limit], True)


def clip_step(step: NewToolStep) -> NewToolStep:
    """Code ≤ 8,000 chars; stdout/stderr ≤ 4,000 each; at most 10 sources of {url, title}.

    A cut field gets a `<field>_truncated: true` flag so the UI can say so.
    Anything else a tool returns (e.g. raw page content) is dropped.
    """
    step_input = dict(step.input)
    if isinstance(step_input.get("code"), str):
        step_input["code"], cut = clip_text(step_input["code"], MAX_CODE_CHARS)
        if cut:
            step_input["code_truncated"] = True
    output = None if step.output is None else _clip_output(step.output)
    return NewToolStep(step.id, step.tool, step.status, step_input, output, step.error_code)


def _clip_output(output: dict[str, Any]) -> dict[str, Any]:
    clipped: dict[str, Any] = {}
    for key in ("stdout", "stderr"):
        if isinstance(output.get(key), str):
            clipped[key], cut = clip_text(output[key], MAX_OUTPUT_CHARS)
            if cut:
                clipped[f"{key}_truncated"] = True
    if "return_code" in output:
        clipped["return_code"] = output["return_code"]
    if isinstance(output.get("sources"), list):
        sources = [s for s in output["sources"] if isinstance(s, dict) and isinstance(s.get("url"), str)]
        clipped["sources"] = [clip_citation(Citation(s["url"], str(s.get("title") or "")))
                              for s in sources[:MAX_SOURCES]]
    return clipped


def clip_citation(citation: Citation) -> dict[str, str]:
    return {"url": citation.url[:MAX_URL_CHARS], "title": citation.title[:MAX_TITLE_CHARS]}


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
    """Delete a conversation and (via cascade) its messages, images, and tool steps.

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
        "SELECT id, role, content, image_refs, citations, created_at FROM messages"
        " WHERE conversation_id = ? ORDER BY created_at, rowid",
        (conversation_id,),
    ).fetchall()
    steps = _tool_steps_by_message(conn, conversation_id)
    messages = [
        {**_message_dict(r), "citations": json.loads(r["citations"]), "tool_steps": steps.get(r["id"], [])}
        for r in rows
    ]
    return {**dict(row), "messages": messages}


def _tool_steps_by_message(conn: sqlite3.Connection, conversation_id: str) -> dict[str, list[dict[str, Any]]]:
    """All tool steps of a conversation's messages, grouped by message, in step order."""
    rows = conn.execute(
        "SELECT s.message_id, s.id, s.seq, s.tool, s.status, s.input, s.output, s.error_code"
        " FROM tool_steps s JOIN messages m ON m.id = s.message_id"
        " WHERE m.conversation_id = ? ORDER BY s.message_id, s.seq",
        (conversation_id,),
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["message_id"], []).append({
            "id": r["id"], "seq": r["seq"], "tool": r["tool"], "status": r["status"],
            "input": json.loads(r["input"]),
            "output": None if r["output"] is None else json.loads(r["output"]),
            "error_code": r["error_code"],
        })
    return grouped


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
