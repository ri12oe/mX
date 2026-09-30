"""mX API.

Run:  uvicorn api.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import db
from api.chat import router as chat_router
from api.config import settings
from api.conversations import router as conversations_router
from api.images import router as images_router
from api.deps import get_db, get_provider, require_key

__all__ = ["app", "get_db", "get_provider", "require_key"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """On startup: set up logging, then create the database and tables if needed."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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

app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(images_router)


@app.get("/health")
def health() -> dict:
    """Public liveness check."""
    return {"status": "ok", "version": app.version}


@app.get("/whoami", dependencies=[Depends(require_key)])
def whoami() -> dict:
    """Protected route to confirm auth works. Removed once the web UI uses /chat."""
    return {
        "assistant": "mX",
        "provider": settings.primary_provider,
        "model": settings.primary_model,
        "provider_key_set": bool(settings.anthropic_api_key),
    }
