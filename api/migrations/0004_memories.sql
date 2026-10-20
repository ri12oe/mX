-- Migration 4: long-term memory (design.md §7, §18).
-- A memory outlives the chat it came from, so source_conversation_id has no foreign key.
-- text is trimmed by the repository; uniqueness is case-insensitive.

CREATE TABLE memories (
    id                      TEXT PRIMARY KEY,
    text                    TEXT NOT NULL CHECK (length(trim(text)) BETWEEN 1 AND 200),
    source_conversation_id  TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE UNIQUE INDEX memories_text_nocase ON memories (text COLLATE NOCASE);
