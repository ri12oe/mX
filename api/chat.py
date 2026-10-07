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
from dataclasses import dataclass, field
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api import db
from api.budget import BudgetStatus, budget_status
from api.config import settings
from api.deps import get_db, get_provider, require_auth
from api.images import ImageError, decode_images
from api.pricing import cost_usd
from api.prompts import MODE_OPTIONS, Mode, SystemPrompt, load_system_prompt
from providers import ModelProvider
from providers.base import ImageData, Message, ModelResponse, SystemPart, UsageMeter
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
    budget_override: bool = Field(
        default=False,
        description="When this month's budget is used up, run this one message with the requested mode anyway.",
    )

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
    mode: Mode
    started: float  # time.monotonic() when the request arrived
    meter: UsageMeter = field(default_factory=UsageMeter)  # filled by the provider while it streams


Usage = ModelResponse | UsageMeter  # both carry the same token/tool counters


@dataclass(frozen=True)
class TurnPolicy:
    """What the server actually applies to this turn after the budget check (design.md §16)."""

    mode: Mode
    tools: bool  # tools allowed (week 2 adds them; off whenever the budget forces brief mode)
    forced: bool  # the budget overrode the requested mode/tools
    budget: BudgetStatus  # the month's state before this turn


def apply_budget(conn: sqlite3.Connection, req: ChatRequest) -> TurnPolicy:
    """At 100% of the month's budget: brief mode, tools off, unless the request overrides it."""
    status = budget_status(conn, settings.monthly_budget_usd)
    forced = status.state == "brief" and not req.budget_override
    return TurnPolicy(mode="brief" if forced else req.mode, tools=not forced, forced=forced, budget=status)


def budget_event(status: BudgetStatus, forced: bool) -> dict[str, Any]:
    """`budget` in the meta and done events."""
    return {
        "state": status.state, "spent_usd": status.spent_usd, "limit_usd": status.limit_usd,
        "resets_at": status.resets_at, "forced": forced,
    }


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
    policy = apply_budget(conn, req)
    pending = start_turn(conn, req, policy.mode)
    prompt = load_system_prompt(policy.mode, settings.system_prompt_file)
    stream = provider.stream(
        pending.history, build_system(prompt), cache_messages=True,
        cache_ttl=settings.cache_ttl, meter=pending.meter, **MODE_OPTIONS[policy.mode],
    )
    next_item = asyncio.ensure_future(anext(stream))
    turn = TurnContext(pending, prompt, provider.name, conn, policy)
    await fail_fast(next_item, turn)
    events = stream_events(stream, next_item, turn)
    return StreamingResponse(events, media_type="text/event-stream", headers=SSE_HEADERS)


# --- Before streaming --------------------------------------------------------


def start_turn(conn: sqlite3.Connection, req: ChatRequest, mode: Mode) -> PendingTurn:
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
        mode=mode,
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


async def fail_fast(next_item: asyncio.Future[str | ModelResponse], turn: "TurnContext") -> None:
    """Wait briefly for the first chunk, so quick failures (bad key, overloaded,
    refused) become HTTP errors. If the model is still thinking after
    FIRST_ITEM_WAIT_SECONDS, start streaming anyway so the connection isn't silent.
    """
    await asyncio.wait({next_item}, timeout=FIRST_ITEM_WAIT_SECONDS)
    if not next_item.done():
        return
    exc = next_item.exception()
    if isinstance(exc, ProviderError):
        turn.record_failure(exc.code, "failed")
        raise HTTPException(
            status_code=http_status_for(exc), detail={"code": exc.code, "message": str(exc)}
        ) from exc
    if isinstance(exc, StopAsyncIteration):
        turn.record_failure("provider_error", "failed")
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


@dataclass
class TurnContext:
    """One turn's state while it streams, plus how its outcome is recorded."""

    pending: PendingTurn
    prompt: SystemPrompt
    provider_name: str
    conn: sqlite3.Connection
    policy: TurnPolicy
    recorded: bool = False  # this turn's spend is in the usage table (or nothing was spent)

    def usage_record(self, usage: Usage, status: db.UsageStatus) -> db.UsageRecord:
        return db.UsageRecord(
            provider=self.provider_name,
            model=usage.model or "unknown",
            prompt_version=self.prompt.version,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=turn_cost(usage),
            latency_ms=elapsed_ms(self.pending),
            mode=self.pending.mode,
            status=status,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_5m_tokens=usage.cache_write_5m_tokens,
            cache_write_1h_tokens=usage.cache_write_1h_tokens,
            web_searches=usage.web_searches,
            code_runs=usage.code_runs,
            requests=usage.requests,
        )

    def save(self, reply: ModelResponse) -> None:
        """Write the whole turn in one transaction (design.md §5)."""
        p = self.pending
        db.save_turn(self.conn, db.Turn(
            conversation_id=p.conversation_id,
            user_message_id=p.user_message_id,
            user_content=p.user_content,
            user_created_at=p.user_created_at,
            user_images=p.user_images,
            assistant_message_id=p.assistant_message_id,
            assistant_content=reply.text,
            usage=self.usage_record(reply, "ok"),
        ))
        self.recorded = True

    def record_failure(self, log_status: str, status: db.UsageStatus) -> None:
        """Log the outcome and, if any request had started, save what it cost (no content).

        Called at most once per turn. A request that never started cost
        nothing, so no row is written for it.
        """
        if self.recorded:
            return
        self.recorded = True
        meter = self.pending.meter
        log_turn(self.pending, status=log_status, usage=meter, cost=turn_cost(meter) if meter.requests else None)
        if not meter.requests:
            return
        try:
            db.save_spend(self.conn, self.usage_record(meter, status))
        except sqlite3.Error:
            logger.exception("Saving the spend of a %s turn failed (conversation=%s)",
                             status, self.pending.conversation_id)


async def stream_events(
    stream: AsyncIterator[str | ModelResponse],
    next_item: asyncio.Future[str | ModelResponse],
    turn: TurnContext,
) -> AsyncIterator[str]:
    pending = turn.pending
    try:
        policy = turn.policy
        yield sse("meta", {
            "conversation_id": pending.conversation_id,
            "message_id": pending.assistant_message_id,
            "mode": policy.mode,
            "tools": policy.tools,
            "budget": budget_event(policy.budget, policy.forced),
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
            turn.record_failure(exc.code, "failed")
            yield sse("error", {"code": exc.code, "message": str(exc)})
            return
        except StopAsyncIteration:
            turn.record_failure("provider_error", "failed")
            yield sse("error", {"code": "provider_error", "message": "Reply ended without a final message."})
            return
        except Exception:
            # A bug or an unexpected SDK error: tell the client instead of silently cutting the stream.
            logger.exception("Unexpected error while streaming (conversation=%s)", pending.conversation_id)
            turn.record_failure("internal_error", "failed")
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
        try:
            turn.save(reply)
        except sqlite3.Error:
            logger.exception("Saving turn failed (conversation=%s)", pending.conversation_id)
            turn.record_failure("save_failed", "failed")
            yield sse("error", {"code": "save_failed", "message": "The reply couldn't be saved."})
            return

        cost = turn_cost(reply)
        log_turn(pending, status="ok", usage=reply, cost=cost)
        after = budget_status(turn.conn, settings.monthly_budget_usd)
        yield sse("done", {
            "usage": usage_event(reply, cost),
            "stop_reason": reply.stop_reason,
            "budget": budget_event(after, policy.forced),
        })
    finally:
        # Anything that ends the turn without recording it (the browser disconnected,
        # the server is shutting down) is an aborted turn; its spend is still saved.
        with anyio.CancelScope(shield=True):
            turn.record_failure("aborted", "aborted")


# --- Helpers -----------------------------------------------------------------


def sse(event: str, data: dict[str, Any]) -> str:
    """One Server-Sent Event. json.dumps escapes newlines, so data stays on one line."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def elapsed_ms(pending: PendingTurn) -> int:
    return int((time.monotonic() - pending.started) * 1000)


def turn_cost(usage: Usage) -> float | None:
    """Everything the turn cost: tokens at their cache rates plus tool fees (design.md §9.1)."""
    if usage.model is None:
        return None
    return cost_usd(
        usage.model, usage.input_tokens, usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_5m_tokens=usage.cache_write_5m_tokens,
        cache_write_1h_tokens=usage.cache_write_1h_tokens,
        web_searches=usage.web_searches,
        code_runs=usage.code_runs,
    )


def usage_event(reply: ModelResponse, cost: float | None) -> dict[str, Any]:
    """`done.usage` (design.md §5). Cache writes are reported as one number (5m + 1h)."""
    return {
        "model": reply.model,
        "input_tokens": reply.input_tokens,
        "output_tokens": reply.output_tokens,
        "cache_read_tokens": reply.cache_read_tokens,
        "cache_write_tokens": reply.cache_write_5m_tokens + reply.cache_write_1h_tokens,
        "web_searches": reply.web_searches,
        "code_runs": reply.code_runs,
        "cost_usd": cost,
    }


def log_turn(pending: PendingTurn, status: str, usage: Usage, cost: float | None = None) -> None:
    """One line per turn. Never logs message content, images, or keys (design.md §10)."""
    level = logging.INFO if status == "ok" else logging.WARNING
    logger.log(
        level,
        "chat turn conversation=%s status=%s mode=%s model=%s requests=%d in=%d out=%d "
        "cache_read=%d cache_write=%d searches=%d code_runs=%d cost_usd=%s latency_ms=%d",
        pending.conversation_id,
        status,
        pending.mode,
        usage.model or "-",
        usage.requests,
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_5m_tokens + usage.cache_write_1h_tokens,
        usage.web_searches,
        usage.code_runs,
        cost if cost is not None else "-",
        elapsed_ms(pending),
    )
