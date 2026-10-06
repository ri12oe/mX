"""POST /chat: send a message, stream the reply as Server-Sent Events (design.md §5, §6).

Event stream: `meta` → `delta`* → `done`, or `error` if something fails after
streaming started. Failures in the first few seconds are normal HTTP errors.
While the model is thinking, a `: ping` comment is sent every few seconds so
proxies (e.g. Fly.io's 60 s idle timeout) don't drop the connection.
A turn is saved only after the reply completes; on any failure nothing is saved.
"""
import asyncio
import json
import logging
import math
import sqlite3
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api import db
from api.config import settings
from api.deps import get_db, get_provider, require_auth
from api.images import ImageError, decode_images
from api.pricing import cost_usd
from api.prompts import MODE_OPTIONS, Mode, SystemPrompt, load_system_prompt
from providers import ModelProvider
from providers.base import ImageData, Message, ModelResponse, SystemPart
from providers.errors import (
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderUnavailableError,
)

logger = logging.getLogger("mx.chat")
router = APIRouter()

MAX_MESSAGE_CHARS = 20_000
MAX_BODY_BYTES = 30 * 1024 * 1024  # fits 4 × 5 MB images as base64 (+33%) plus text
HISTORY_WINDOW = 20  # max messages sent to the model, including the new one
HISTORY_STEP = 10  # the window's start moves in steps, so the cached prefix lasts 5 turns (§6.1)
IMAGE_OMITTED = "[image omitted]"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
FIRST_ITEM_WAIT_SECONDS = 10.0  # quick failures within this become HTTP errors
HEARTBEAT_SECONDS = 15.0  # comment line sent while waiting for the model
HEARTBEAT = ": ping\n\n"


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    images: list[str] = Field(
        default_factory=list,
        description="Up to 4 base64 images (JPEG, PNG, GIF, WebP; max 5 MB each). A data: URL is also accepted.",
    )
    mode: Mode = "normal"

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


@dataclass(frozen=True)
class PendingTurn:
    """Everything about a turn that's known before the model replies."""

    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    user_content: str
    user_created_at: str
    user_images: tuple[db.NewImage, ...]
    history: list[Message]
    started: float  # time.monotonic() when the request arrived


def limit_body_size(request: Request) -> None:
    """Reject oversized requests (413) based on their declared size."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large")


@router.post("/chat", dependencies=[Depends(require_auth), Depends(limit_body_size)])
async def chat(
    req: ChatRequest,
    conn: sqlite3.Connection = Depends(get_db),
    provider: ModelProvider = Depends(get_provider),
) -> StreamingResponse:
    """Send a message to mX; the reply streams back as Server-Sent Events."""
    pending = start_turn(conn, req)
    prompt = load_system_prompt(req.mode, settings.system_prompt_file)
    stream = provider.stream(
        pending.history, build_system(prompt),
        cache_messages=True, cache_ttl=settings.cache_ttl, **MODE_OPTIONS[req.mode],
    )
    next_item = asyncio.ensure_future(anext(stream))
    await fail_fast(next_item, pending)
    events = stream_events(stream, next_item, pending, prompt, provider.name, conn)
    return StreamingResponse(events, media_type="text/event-stream", headers=SSE_HEADERS)


# --- Before streaming --------------------------------------------------------


def start_turn(conn: sqlite3.Connection, req: ChatRequest) -> PendingTurn:
    """Check images (422) and the conversation (404), then build the history to send."""
    started = time.monotonic()
    try:
        images = decode_images(req.images)
    except ImageError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "invalid_image", "message": str(exc)}
        ) from None
    if req.conversation_id is None:
        conversation_id, stored = db.new_id(), []
    elif db.conversation_exists(conn, req.conversation_id):
        conversation_id = req.conversation_id
        stored = load_window(conn, conversation_id)
    else:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return PendingTurn(
        conversation_id=conversation_id,
        user_message_id=db.new_id(),
        assistant_message_id=db.new_id(),
        user_content=req.message,
        user_created_at=db.now_iso(),
        user_images=tuple(db.NewImage(db.new_id(), i.media_type, i.data) for i in images),
        history=build_history(stored, req.message, images),
        started=started,
    )


def window_start(total: int) -> int:
    """Index of the first message to send, out of `total` (stored + the new one).

    All of them up to HISTORY_WINDOW; after that the start jumps forward
    HISTORY_STEP messages at a time, so between 11 and 20 are sent and the
    start (and the cached prefix) stays put for 5 turns (design.md §6.1, §15).
    """
    if total <= HISTORY_WINDOW:
        return 0
    return HISTORY_STEP * math.ceil((total - HISTORY_WINDOW) / HISTORY_STEP)


def load_window(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    """The stored messages from the window start on, oldest first."""
    stored = db.count_messages(conn, conversation_id)
    start = window_start(stored + 1)
    return db.get_recent_messages(conn, conversation_id, limit=stored - start)


def build_system(prompt: SystemPrompt) -> list[SystemPart]:
    """The system prompt as cacheable parts (design.md §15). The learner profile joins in week 4."""
    return [SystemPart(prompt.text, cache=True)]


def build_history(
    stored: list[dict[str, Any]], new_message: str, images: list[ImageData] | None = None
) -> list[Message]:
    """Past messages plus the new one. Must start with a user message.

    Only the new message carries images; older images are replaced by a text
    marker so the model knows one was there (design.md §6).
    """
    messages = [Message(role=m["role"], content=with_image_markers(m)) for m in stored]
    while messages and messages[0].role != "user":
        messages.pop(0)
    return [*messages, Message(role="user", content=new_message, images=images or None)]


def with_image_markers(message: dict[str, Any]) -> str:
    markers = [IMAGE_OMITTED] * len(message["image_refs"])
    return "\n".join([*markers, message["content"]])


async def fail_fast(next_item: asyncio.Future[str | ModelResponse], pending: PendingTurn) -> None:
    """Wait briefly for the first chunk, so quick failures (bad key, overloaded,
    refused) become HTTP errors. If the model is still thinking after
    FIRST_ITEM_WAIT_SECONDS, start streaming anyway so the connection isn't silent.
    """
    await asyncio.wait({next_item}, timeout=FIRST_ITEM_WAIT_SECONDS)
    if not next_item.done():
        return
    exc = next_item.exception()
    if isinstance(exc, ProviderError):
        log_turn(pending, status=exc.code)
        raise HTTPException(
            status_code=http_status_for(exc), detail={"code": exc.code, "message": str(exc)}
        ) from exc
    if isinstance(exc, StopAsyncIteration):
        log_turn(pending, status="provider_error")
        raise HTTPException(
            status_code=502, detail={"code": "provider_error", "message": "Empty reply stream."}
        ) from None


def http_status_for(exc: ProviderError) -> int:
    if isinstance(exc, (ProviderRateLimitError, ProviderUnavailableError)):
        return 503  # temporary: try again later
    if isinstance(exc, ProviderRefusalError):
        return 422  # the model declined this request
    return 502  # auth, bad request, unknown provider: our side / upstream problem


# --- Streaming ---------------------------------------------------------------


async def stream_events(
    stream: AsyncIterator[str | ModelResponse],
    next_item: asyncio.Future[str | ModelResponse],
    pending: PendingTurn,
    prompt: SystemPrompt,
    provider_name: str,
    conn: sqlite3.Connection,
) -> AsyncIterator[str]:
    yield sse("meta", {
        "conversation_id": pending.conversation_id,
        "message_id": pending.assistant_message_id,
    })
    try:
        while True:
            while not next_item.done():
                await asyncio.wait({next_item}, timeout=HEARTBEAT_SECONDS)
                if not next_item.done():
                    yield HEARTBEAT
            item = next_item.result()
            if isinstance(item, ModelResponse):
                break
            yield sse("delta", {"text": item})
            next_item = asyncio.ensure_future(anext(stream))
    except ProviderError as exc:
        log_turn(pending, status=exc.code)
        yield sse("error", {"code": exc.code, "message": str(exc)})
        return
    except StopAsyncIteration:
        log_turn(pending, status="provider_error")
        yield sse("error", {"code": "provider_error", "message": "Reply ended without a final message."})
        return
    except Exception:
        # A bug or an unexpected SDK error: tell the client instead of silently cutting the stream.
        logger.exception("Unexpected error while streaming (conversation=%s)", pending.conversation_id)
        log_turn(pending, status="internal_error")
        yield sse("error", {"code": "internal_error", "message": "Something went wrong on the server."})
        return
    finally:
        # Close the model stream even if the client disconnected (shielded from
        # cancellation), so we stop paying for text nobody will read.
        with anyio.CancelScope(shield=True):
            if not next_item.done():
                next_item.cancel()
                try:
                    await next_item
                except (asyncio.CancelledError, Exception):
                    pass
            await stream.aclose()

    reply = item
    cost = cost_usd(reply.model, reply.input_tokens, reply.output_tokens)
    try:
        save(conn, pending, reply, prompt, provider_name, cost)
    except sqlite3.Error:
        logger.exception("Saving turn failed (conversation=%s)", pending.conversation_id)
        log_turn(pending, status="save_failed", reply=reply, cost=cost)
        yield sse("error", {"code": "save_failed", "message": "The reply couldn't be saved."})
        return

    log_turn(pending, status="ok", reply=reply, cost=cost)
    yield sse("done", {
        "usage": {
            "model": reply.model,
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "cost_usd": cost,
        },
        "stop_reason": reply.stop_reason,
    })


def save(
    conn: sqlite3.Connection,
    pending: PendingTurn,
    reply: ModelResponse,
    prompt: SystemPrompt,
    provider_name: str,
    cost: float | None,
) -> None:
    """Write the whole turn in one transaction (design.md §5)."""
    db.save_turn(conn, db.Turn(
        conversation_id=pending.conversation_id,
        user_message_id=pending.user_message_id,
        user_content=pending.user_content,
        user_created_at=pending.user_created_at,
        user_images=pending.user_images,
        assistant_message_id=pending.assistant_message_id,
        assistant_content=reply.text,
        usage=db.UsageRecord(
            provider=provider_name,
            model=reply.model,
            prompt_version=prompt.version,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            cost_usd=cost,
            latency_ms=elapsed_ms(pending),
        ),
    ))


# --- Helpers -----------------------------------------------------------------


def sse(event: str, data: dict[str, Any]) -> str:
    """One Server-Sent Event. json.dumps escapes newlines, so data stays on one line."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def elapsed_ms(pending: PendingTurn) -> int:
    return int((time.monotonic() - pending.started) * 1000)


def log_turn(
    pending: PendingTurn,
    status: str,
    reply: ModelResponse | None = None,
    cost: float | None = None,
) -> None:
    """One line per turn. Never logs message content, images, or keys (design.md §10)."""
    level = logging.INFO if status == "ok" else logging.WARNING
    logger.log(
        level,
        "chat turn conversation=%s status=%s model=%s in=%s out=%s cost_usd=%s latency_ms=%d",
        pending.conversation_id,
        status,
        reply.model if reply else "-",
        reply.input_tokens if reply else "-",
        reply.output_tokens if reply else "-",
        cost if cost is not None else "-",
        elapsed_ms(pending),
    )
