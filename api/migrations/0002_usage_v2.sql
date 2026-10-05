-- Migration 2: usage v2 (design.md §7, §16).
-- - message_id becomes nullable and ON DELETE SET NULL: deleting a chat keeps its
--   spend (so the monthly budget can't be lowered by deleting chats), and failed or
--   stopped turns can record what they cost without a saved message.
-- - New: mode, status, cache and tool counters, number of API requests.
-- SQLite can't change a column's constraints in place, so the table is copied.
-- Old rows: mode = NULL (unknown), status 'ok', counters 0, requests 1.

CREATE TABLE usage_new (
    id                     TEXT PRIMARY KEY,
    message_id             TEXT REFERENCES messages (id) ON DELETE SET NULL,
    provider               TEXT NOT NULL,
    model                  TEXT NOT NULL,
    prompt_version         TEXT NOT NULL,
    mode                   TEXT CHECK (mode IN ('normal', 'brief')),  -- NULL = unknown (before v2)
    status                 TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'failed', 'aborted')),
    input_tokens           INTEGER NOT NULL,
    output_tokens          INTEGER NOT NULL,
    cache_read_tokens      INTEGER NOT NULL DEFAULT 0,
    cache_write_5m_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_1h_tokens  INTEGER NOT NULL DEFAULT 0,
    web_searches           INTEGER NOT NULL DEFAULT 0,
    code_runs              INTEGER NOT NULL DEFAULT 0,
    requests               INTEGER NOT NULL DEFAULT 1,
    cost_usd               REAL,  -- NULL when the model has no price in api/pricing.py
    latency_ms             INTEGER NOT NULL,
    created_at             TEXT NOT NULL
);

INSERT INTO usage_new (id, message_id, provider, model, prompt_version,
                       input_tokens, output_tokens, cost_usd, latency_ms, created_at)
    SELECT id, message_id, provider, model, prompt_version,
           input_tokens, output_tokens, cost_usd, latency_ms, created_at
    FROM usage;

DROP TABLE usage;
ALTER TABLE usage_new RENAME TO usage;

CREATE INDEX idx_usage_message ON usage (message_id);
CREATE INDEX idx_usage_created_at ON usage (created_at);  -- month and day sums
