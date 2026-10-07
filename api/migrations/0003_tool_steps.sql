-- Migration 3: tool steps and citations (design.md §7, §17).
-- - tool_steps: one row per tool step of an assistant message (code run, web search),
--   seq from 0, saved in the same transaction as the turn. Inputs and outputs are
--   stored clipped (api/db.py) and never include raw search-result content.
-- - messages.citations: JSON list of {url, title} the answer cited; '[]' when none.

CREATE TABLE tool_steps (
    id          TEXT PRIMARY KEY,
    message_id  TEXT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    tool        TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    input       TEXT NOT NULL,  -- JSON object
    output      TEXT,           -- JSON object, NULL if the step produced none
    error_code  TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (message_id, seq)
);

ALTER TABLE messages ADD COLUMN citations TEXT NOT NULL DEFAULT '[]';
