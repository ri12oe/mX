"""FastAPI dependencies shared by routes. Tests override these via app.dependency_overrides."""
import hmac
import sqlite3
from collections.abc import Iterator
from functools import lru_cache

from fastapi import Header, HTTPException

from api import db
from api.config import settings
from providers import ModelProvider, create_provider


def get_db() -> Iterator[sqlite3.Connection]:
    """One SQLite connection per request, always closed afterwards.

    For streaming routes, FastAPI runs the cleanup after the response has been
    fully sent, so the connection stays open while the stream saves the turn.
    """
    conn = db.connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


@lru_cache
def get_provider() -> ModelProvider:
    """The configured model provider, built once and shared (reuses the SDK client).

    Routes use only this, never an SDK.
    """
    return create_provider(
        settings.primary_provider,
        api_key=settings.anthropic_api_key,
        model=settings.primary_model,
    )


def require_key(x_mx_key: str = Header(default="")) -> None:
    """Every protected route requires the X-mX-Key header.

    Uses a constant-time compare so response timing doesn't leak the key.
    """
    if not hmac.compare_digest(x_mx_key.encode(), settings.mx_api_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing X-mX-Key")
