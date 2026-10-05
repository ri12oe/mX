"""Schema migrations and pre-migration backups (design.md §7.1).

`api/migrations/NNNN_name.sql` files upgrade the database one version at a
time; `PRAGMA user_version` records the version reached. Before upgrading a
database that already has data, it is copied to `<DB dir>/backups/`.
Each step is one transaction, so a failed step leaves the database at the
last good version and mX refuses to start.
"""
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from api.db import SchemaVersionError, connect

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
BACKUP_DIR_NAME = "backups"
_FILE_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

log = logging.getLogger(__name__)


class MigrationError(RuntimeError):
    """A migration or the backup before it failed; the app must not start."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """All migration files in order. Numbers must run 1, 2, 3… with no gaps."""
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_NAME.match(path.name)
        if match is None:
            raise MigrationError(f"Bad migration file name: {path.name} (expected NNNN_name.sql)")
        migrations.append(Migration(int(match.group(1)), path.name, path.read_text(encoding="utf-8")))
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(f"Migrations must be numbered 1, 2, 3…; found {migration.name}")
    if not migrations:
        raise MigrationError(f"No migrations found in {directory}")
    return migrations


TARGET_VERSION = load_migrations()[-1].version


def migrate(
    db_path: str | Path, directory: Path = MIGRATIONS_DIR, now: datetime | None = None
) -> Path | None:
    """Bring the database up to the newest version. Returns the backup path, if one was made.

    Raises SchemaVersionError for a database newer than this code and
    MigrationError for anything else that should stop startup.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = load_migrations(directory)
    target = migrations[-1].version
    conn = connect(path)
    conn.isolation_level = None  # autocommit; each step manages its own transaction
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > target:
            raise SchemaVersionError(f"Database schema v{version} is newer than this code (v{target}).")
        conn.execute("PRAGMA journal_mode = WAL")
        if version == target:
            return None
        if version == 0 and _has_tables(conn):
            raise MigrationError(
                f"{path} has tables but no schema version; it wasn't made by mX. Not touching it."
            )
        backup = _backup(conn, path, version, now) if version > 0 else None
        for migration in migrations[version:]:
            _apply(conn, migration)
        return backup
    finally:
        conn.close()


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    return row.fetchone() is not None


def _backup(conn: sqlite3.Connection, path: Path, version: int, now: datetime | None) -> Path:
    """Copy the whole database (safe with WAL) before changing it. Never deleted automatically."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    target = path.parent / BACKUP_DIR_NAME / f"{path.stem}-v{version}-{stamp}.db"
    try:
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            raise FileExistsError(f"{target} already exists")
    except OSError as exc:
        raise MigrationError(f"Couldn't back up the database before upgrading: {exc}") from exc
    copy = sqlite3.connect(target)
    try:
        conn.backup(copy)
    except sqlite3.Error as exc:
        copy.close()
        target.unlink(missing_ok=True)  # never leave a half-written backup behind
        raise MigrationError(f"Couldn't back up the database before upgrading: {exc}") from exc
    copy.close()
    log.info("backed up database (v%d) to %s", version, target)
    return target


def _apply(conn: sqlite3.Connection, migration: Migration) -> None:
    """One step in one transaction, with the version bump inside it.

    Foreign keys are off during the step (so tables can be rebuilt) and
    checked before committing.
    """
    started = time.perf_counter()
    conn.execute("PRAGMA foreign_keys = OFF")  # has no effect inside a transaction
    try:
        conn.executescript(f"BEGIN;\n{migration.sql}\n;PRAGMA user_version = {migration.version};")
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise MigrationError(f"{len(problems)} foreign key problem(s) after {migration.name}")
        conn.execute("COMMIT")
    except (sqlite3.Error, MigrationError) as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        log.error("migration %s failed; database left at v%d", migration.name, migration.version - 1)
        raise MigrationError(f"Migration {migration.name} failed: {exc}") from exc
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    log.info("migrated v%d → v%d in %d ms", migration.version - 1, migration.version, elapsed_ms)
