"""mX API.

Run:  uvicorn api.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""
import hmac
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api import db
from api.config import settings
from providers import ModelProvider, create_provider


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """On startup, create the database and tables if they don't exist yet."""
    db.init_db(settings.db_path)
    yield


app = FastAPI(title="mX API", version="0.1.0", lifespan=lifespan)

# Lets the React dev server (a different origin) call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-mX-Key", "Content-Type"],
)


def get_db() -> Iterator[sqlite3.Connection]:
    """One SQLite connection per request, always closed afterwards.

    Tests can swap it with app.dependency_overrides[get_db].
    """
    conn = db.connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


@lru_cache
def get_provider() -> ModelProvider:
    """The configured model provider, built once and shared (reuses the SDK client).

    Routes use only this, never an SDK. Tests swap in a fake with
    app.dependency_overrides[get_provider].
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


@app.get("/health")
def health() -> dict:
    """Public liveness check."""
    return {"status": "ok", "version": app.version}


@app.get("/whoami", dependencies=[Depends(require_key)])
def whoami() -> dict:
    """Protected route to confirm auth works. Replaced by /chat in Week 2."""
    return {
        "assistant": "mX",
        "provider": settings.primary_provider,
        "model": settings.primary_model,
        "provider_key_set": bool(settings.anthropic_api_key),
    }
