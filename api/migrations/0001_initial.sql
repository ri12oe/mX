-- Migration 1: the Phase 1 schema (design.md §7), moved from api/schema.sql.
-- IDs are UUID4 text. Timestamps are ISO-8601 UTC text.
-- Never edit a migration after it ships; add a new NNNN_name.sql instead (design.md §7.1).

CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
    ON conversations (updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    image_refs       TEXT NOT NULL DEFAULT '[]',  -- JSON list of image ids
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS images (
    id          TEXT PRIMARY KEY,
    message_id  TEXT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    media_type  TEXT NOT NULL,
    data        BLOB NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_images_message
    ON images (message_id);

CREATE TABLE IF NOT EXISTS usage (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    cost_usd        REAL,  -- NULL when the model has no price in api/pricing.py
    latency_ms      INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_message
    ON usage (message_id);
