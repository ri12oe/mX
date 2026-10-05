"""Shared test setup. Runs before any test module imports the app.

Sets a known test key and a throwaway database path so tests never depend
on the developer's .env or touch the real data/mx.db.
Environment variables take priority over .env in pydantic-settings.
"""
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_API_KEY = "test-key-" + "x" * 40
TEST_PASSWORD = "correct horse battery staple"
TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="mx-test-"))

os.environ["MX_API_KEY"] = TEST_API_KEY
os.environ["MX_PASSWORD"] = TEST_PASSWORD
os.environ["DB_PATH"] = str(TEST_DB_DIR / "app.db")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A fresh, fully set-up database for one test."""
    from api import db
    from api.migrate import migrate

    path = tmp_path / "test.db"
    migrate(path)
    connection = db.connect(path)
    yield connection
    connection.close()
