"""mX API (and, when built, the web app at /).

Run:  uvicorn api.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.auth import router as auth_router
from api.chat import router as chat_router
from api.config import settings
from api.conversations import router as conversations_router
from api.deps import get_db, get_provider, require_auth
from api.images import router as images_router
from api.migrate import migrate
from api.usage import router as usage_router

__all__ = ["app", "get_db", "get_provider", "require_auth"]

# Scripts and styles only from this site; images may be data:/blob: (uploads, previews).
# 'unsafe-inline' styles are needed by KaTeX's math layout; no inline scripts are allowed.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
# FastAPI's interactive docs load their scripts from a CDN, which the CSP would block.
DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """On startup: set up logging, then create or upgrade the database (backing it up first)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    migrate(settings.db_path)
    yield


app = FastAPI(title="mX API", version="0.1.0", lifespan=lifespan)

# For a web app served from another origin. In production the app is same-origin, so this is unused.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-mX-Key", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        if name == "Content-Security-Policy" and request.url.path in DOCS_PATHS:
            continue
        response.headers.setdefault(name, value)
    return response


app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(images_router)
app.include_router(usage_router)


@app.get("/health")
def health() -> dict:
    """Public liveness check."""
    return {"status": "ok", "version": app.version}


@app.get("/whoami", dependencies=[Depends(require_auth)])
def whoami() -> dict:
    """Who am I talking to? Also how the web app checks that it's signed in."""
    return {
        "assistant": "mX",
        "provider": settings.primary_provider,
        "model": settings.primary_model,
        "provider_key_set": bool(settings.anthropic_api_key),
    }


def mount_web_app(app: FastAPI, dist: Path) -> bool:
    """Serve the built React app at / (after all API routes, so they take priority)."""
    if not (dist / "index.html").is_file():
        return False
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return True


mount_web_app(app, Path(settings.web_dist))
