"""Migration runner and pre-migration backups (design.md §7.1)."""
import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from api import db
from api.migrate import (
    MIGRATIONS_DIR,
    TARGET_VERSION,
    MigrationError,
    load_migrations,
    migrate,
)

NOW = datetime(2026, 10, 5, 15, 30, 0, tzinfo=timezone.utc)
T0 = "2026-10-01T10:00:00.000000+00:00"

# A realistic step 2: rebuild a table with foreign keys pointing at it (the 0002 pattern).
REBUILD_MESSAGES = """
CREATE TABLE messages_new (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    image_refs       TEXT NOT NULL DEFAULT '[]',
    pinned           INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);
INSERT INTO messages_new (id, conversation_id, role, content, image_refs, created_at)
    SELECT id, conversation_id, role, content, image_refs, created_at FROM messages;
DROP TABLE messages;
ALTER TABLE messages_new RENAME TO messages;
CREATE INDEX idx_messages_conversation ON messages (conversation_id, created_at);
"""


def migrations_dir(tmp_path: Path, name: str = "migrations", **extra: str) -> Path:
    """The real 0001 plus extra steps, e.g. migrations_dir(tmp, **{"0002_x": "SQL"})."""
    directory = tmp_path / name
    directory.mkdir()
    shutil.copy(MIGRATIONS_DIR / "0001_initial.sql", directory)
    for step, sql in extra.items():
        (directory / f"{step}.sql").write_text(sql, encoding="utf-8")
    return directory


def v1_database_with_data(path: Path) -> None:
    """A Phase 1 database (schema v1 only) with one turn, an image, and its usage row.

    Rows are inserted with v1-shaped SQL, exactly as Phase 1 code wrote them.
    """
    migrate(path, migrations_dir(path.parent, name="v1-only"))
    conn = db.connect(path)
    with conn:
        conn.execute("INSERT INTO conversations VALUES ('c1', 'Hello', ?, ?)", (T0, T0))
        conn.execute("INSERT INTO messages VALUES ('u1', 'c1', 'user', 'Hello', '[\"i1\"]', ?)", (T0,))
        conn.execute("INSERT INTO messages VALUES ('a1', 'c1', 'assistant', 'Hi there', '[]', ?)", (T0,))
        conn.execute("INSERT INTO images VALUES ('i1', 'u1', 'image/png', ?, ?)", (b"\x89PNG fake", T0))
        conn.execute(
            "INSERT INTO usage VALUES ('g1', 'a1', 'anthropic', 'claude-opus-5-5', 'mx_system_v3',"
            " 100, 50, 0.0014, 900, ?)", (T0,),
        )
    conn.close()


def version(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def counts(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("conversations", "messages", "images", "usage")}
    finally:
        conn.close()


def tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


# --- The shipped migrations ------------------------------------------------


def test_shipped_migrations_are_numbered_from_one():
    migrations = load_migrations()
    assert [m.version for m in migrations] == list(range(1, TARGET_VERSION + 1))
    assert migrations[0].name == "0001_initial.sql"


# --- Fresh and current databases -------------------------------------------


def test_fresh_database_gets_every_step_and_no_backup(tmp_path: Path):
    path = tmp_path / "data" / "mx.db"  # parent folder doesn't exist yet
    assert migrate(path) is None
    assert version(path) == TARGET_VERSION
    assert {"conversations", "messages", "images", "usage"} <= tables(path)
    assert not (path.parent / "backups").exists()


def test_fresh_database_runs_all_steps_in_order(tmp_path: Path):
    directory = migrations_dir(tmp_path, **{"0002_rebuild": REBUILD_MESSAGES})
    path = tmp_path / "mx.db"
    assert migrate(path, directory) is None
    assert version(path) == 2


def test_current_database_is_left_alone(tmp_path: Path):
    path = tmp_path / "mx.db"
    v1_database_with_data(path)
    migrate(path)  # up to date now (makes one backup)
    backups = list((tmp_path / "backups").iterdir())
    before = counts(path)
    assert migrate(path) is None
    assert counts(path) == before
    assert list((tmp_path / "backups").iterdir()) == backups  # no new backup


def test_refuses_a_database_from_newer_code(tmp_path: Path):
    path = tmp_path / "future.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {TARGET_VERSION + 1}")
    conn.close()
    with pytest.raises(db.SchemaVersionError):
        migrate(path)
    assert version(path) == TARGET_VERSION + 1


def test_refuses_an_unversioned_database_that_has_tables(tmp_path: Path):
    path = tmp_path / "other.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (id INTEGER)")
    conn.close()
    with pytest.raises(MigrationError, match="no schema version"):
        migrate(path)
    assert tables(path) == {"notes"}


# --- Upgrading a database with data ----------------------------------------


def test_upgrade_backs_up_first_and_keeps_every_row(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    path = tmp_path / "mx.db"
    v1_database_with_data(path)
    before = counts(path)
    directory = migrations_dir(tmp_path, **{"0002_rebuild": REBUILD_MESSAGES})

    with caplog.at_level(logging.INFO, logger="api.migrate"):
        backup = migrate(path, directory, now=NOW)

    assert version(path) == 2
    assert counts(path) == before
    conn = db.connect(path)
    assert tuple(conn.execute("SELECT content, pinned FROM messages WHERE id = 'a1'").fetchone()) == ("Hi there", 0)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    db.delete_conversation(conn, "c1")  # cascades still work through the rebuilt table
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    conn.close()

    assert backup == tmp_path / "backups" / "mx-v1-20261005T153000Z.db"
    assert version(backup) == 1
    assert counts(backup) == before
    assert "migrated v1 → v2" in caplog.text
    assert "Hello" not in caplog.text  # never log content


def test_failed_step_rolls_back_and_keeps_the_last_good_version(tmp_path: Path):
    path = tmp_path / "mx.db"
    v1_database_with_data(path)
    broken = "CREATE TABLE half_done (id TEXT);\nTHIS IS NOT SQL;"
    directory = migrations_dir(tmp_path, **{"0002_broken": broken})

    with pytest.raises(MigrationError, match="0002_broken.sql"):
        migrate(path, directory, now=NOW)

    assert version(path) == 1
    assert "half_done" not in tables(path)
    assert counts(path)["messages"] == 2
    assert version(tmp_path / "backups" / "mx-v1-20261005T153000Z.db") == 1


def test_step_that_breaks_foreign_keys_is_rolled_back(tmp_path: Path):
    path = tmp_path / "mx.db"
    v1_database_with_data(path)
    orphan = "INSERT INTO messages VALUES ('m9', 'no-such-chat', 'user', 'x', '[]', '2026-10-01');"
    directory = migrations_dir(tmp_path, **{"0002_orphan": orphan})

    with pytest.raises(MigrationError, match="foreign key"):
        migrate(path, directory, now=NOW)

    assert version(path) == 1
    assert counts(path)["messages"] == 2


def test_failed_backup_stops_the_upgrade(tmp_path: Path):
    path = tmp_path / "mx.db"
    v1_database_with_data(path)
    (tmp_path / "backups").write_text("a file where the folder should be")
    directory = migrations_dir(tmp_path, **{"0002_rebuild": REBUILD_MESSAGES})

    with pytest.raises(MigrationError, match="back up"):
        migrate(path, directory, now=NOW)
    assert version(path) == 1


def test_never_overwrites_an_existing_backup(tmp_path: Path):
    path = tmp_path / "mx.db"
    v1_database_with_data(path)
    existing = tmp_path / "backups" / "mx-v1-20261005T153000Z.db"
    existing.parent.mkdir()
    existing.write_bytes(b"older backup")
    directory = migrations_dir(tmp_path, **{"0002_rebuild": REBUILD_MESSAGES})

    with pytest.raises(MigrationError, match="already exists"):
        migrate(path, directory, now=NOW)
    assert existing.read_bytes() == b"older backup"
    assert version(path) == 1


# --- 0002: usage v2 --------------------------------------------------------


def schema(path: Path) -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    finally:
        conn.close()


def test_usage_v2_keeps_every_phase1_row_and_sets_defaults(tmp_path: Path):
    path = tmp_path / "mx.db"
    v1_database_with_data(path)
    before = counts(path)

    backup = migrate(path, now=NOW)

    assert version(path) == TARGET_VERSION >= 2
    assert counts(path) == before
    conn = db.connect(path)
    row = dict(conn.execute("SELECT * FROM usage").fetchone())
    assert row == {
        "id": "g1", "message_id": "a1", "provider": "anthropic", "model": "claude-opus-5-5",
        "prompt_version": "mx_system_v3", "mode": None, "status": "ok",
        "input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 0,
        "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0, "web_searches": 0,
        "code_runs": 0, "requests": 1, "cost_usd": 0.0014, "latency_ms": 900, "created_at": T0,
    }
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    indexes = {r[1] for r in conn.execute("PRAGMA index_list(usage)")}
    assert {"idx_usage_message", "idx_usage_created_at"} <= indexes
    conn.close()

    assert backup is not None and version(backup) == 1
    assert counts(backup) == before


def test_usage_v2_deleting_a_chat_keeps_its_spend(tmp_path: Path):
    path = tmp_path / "mx.db"
    v1_database_with_data(path)
    migrate(path)
    conn = db.connect(path)
    assert db.delete_conversation(conn, "c1")
    rows = [tuple(r) for r in conn.execute("SELECT message_id, cost_usd FROM usage")]
    assert rows == [(None, 0.0014)]
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    conn.close()


def test_usage_v2_migrated_and_fresh_schemas_match(tmp_path: Path):
    migrated, fresh = tmp_path / "migrated.db", tmp_path / "fresh.db"
    v1_database_with_data(migrated)
    migrate(migrated)
    migrate(fresh)
    assert schema(migrated) == schema(fresh)


@pytest.mark.parametrize(("column", "value"), [("status", "maybe"), ("mode", "loud")])
def test_usage_v2_rejects_unknown_status_and_mode(conn: sqlite3.Connection, column: str, value: str):
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                f"INSERT INTO usage (id, provider, model, prompt_version, {column},"
                " input_tokens, output_tokens, latency_ms, created_at)"
                " VALUES ('x', 'p', 'm', 'v', ?, 0, 0, 0, ?)", (value, T0),
            )


# --- Loading migration files -----------------------------------------------


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"0001_initial.sql": "", "0003_skip.sql": ""}, "numbered"),
        ({"0002_first.sql": ""}, "numbered"),
        ({"0001_initial.sql": "", "2_bad-name.sql": ""}, "Bad migration file name"),
        ({}, "No migrations"),
    ],
)
def test_load_rejects_bad_sets_of_files(tmp_path: Path, files: dict[str, str], message: str):
    for name, sql in files.items():
        (tmp_path / name).write_text(sql)
    with pytest.raises(MigrationError, match=message):
        load_migrations(tmp_path)
