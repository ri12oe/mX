"""Conversation endpoints: list, get, delete (design.md §5)."""
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from api import db
from api.deps import get_db, require_auth

router = APIRouter(prefix="/conversations", dependencies=[Depends(require_auth)])

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class CitationOut(BaseModel):
    url: str
    title: str


class ToolStepOut(BaseModel):
    """A stored tool step (design.md §7). Input/output are already clipped to stored sizes."""

    id: str
    seq: int
    tool: str
    status: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    error_code: str | None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    image_refs: list[str]
    created_at: str
    citations: list[CitationOut] = []  # Phase 2: sources an answer cited
    tool_steps: list[ToolStepOut] = []  # Phase 2: code runs and searches behind an answer


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]


@router.get("")
def list_conversations(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[ConversationSummary]:
    """Conversations, most recently updated first."""
    return [ConversationSummary(**c) for c in db.list_conversations(conn, limit=limit)]


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str, conn: sqlite3.Connection = Depends(get_db)
) -> ConversationDetail:
    """One conversation with all its messages, oldest first."""
    convo = db.get_conversation(conn, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationDetail(**convo)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str, conn: sqlite3.Connection = Depends(get_db)
) -> Response:
    """Delete a conversation and its messages, images, and tool steps (usage rows are kept, design.md §7)."""
    if not db.delete_conversation(conn, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)
