"""Memory endpoints (design.md §5, §18). Nothing is stored until Rio asks."""
import sqlite3
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from api import db
from api.deps import get_db, require_auth

router = APIRouter(prefix="/memories", dependencies=[Depends(require_auth)])

_MESSAGES = {
    "blank": "Memory text can't be blank.",
    "too_long": f"Memories are limited to {db.MEMORY_TEXT_MAX} characters.",
    "memory_limit": f"Memory limit reached ({db.MEMORY_LIMIT}). Remove one first.",
    "memory_duplicate": "That memory is already saved.",
}


class MemoryIn(BaseModel):
    text: str
    source_conversation_id: str | None = None


class MemoryPatch(BaseModel):
    text: str


class MemoryOut(BaseModel):
    id: str
    text: str
    source_conversation_id: str | None
    created_at: str
    updated_at: str


def _reject(exc: db.MemoryRejected) -> NoReturn:
    status = 422 if exc.code in ("blank", "too_long") else 409
    raise HTTPException(status_code=status, detail={"code": exc.code, "message": _MESSAGES[exc.code]})


@router.get("")
def list_memories(conn: sqlite3.Connection = Depends(get_db)) -> list[MemoryOut]:
    """All memories, oldest first."""
    return [MemoryOut(**row) for row in db.list_memories(conn)]


@router.post("", status_code=201)
def create_memory(body: MemoryIn, conn: sqlite3.Connection = Depends(get_db)) -> MemoryOut:
    try:
        row = db.add_memory(conn, body.text, body.source_conversation_id)
    except db.MemoryRejected as exc:
        _reject(exc)
    return MemoryOut(**row)


@router.patch("/{memory_id}")
def patch_memory(memory_id: str, body: MemoryPatch, conn: sqlite3.Connection = Depends(get_db)) -> MemoryOut:
    try:
        row = db.update_memory(conn, memory_id, body.text)
    except db.MemoryRejected as exc:
        _reject(exc)
    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryOut(**row)


@router.delete("/{memory_id}", status_code=204)
def remove_memory(memory_id: str, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    if not db.delete_memory(conn, memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return Response(status_code=204)
