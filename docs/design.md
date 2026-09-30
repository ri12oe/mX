# mX — Design Doc (v0.3, Phase 1)

Owner: Rio · Status: Reviewed · Last updated: 2026-09-30

> v0.3 change (2026-09-30): architect review applied. Defines the SSE format, image storage,
> DB approach, turn saving, history limits, prompt loading, pricing, errors, auth hardening,
> CORS, logging, and testing. Prompt loader and cost logging moved into Week 2.

## 1. Goal
A personal AI assistant ("mX") that Rio can chat with through his **own backend**,
built on hosted model APIs. Phase 1 delivers the brain, personality, and API layer.
Later phases add tools, memory, voice, context awareness, and AR-glasses clients.

## 2. Principles
1. **Backend-first.** Every client (web, phone, voice, glasses) talks to the mX API, never to a model provider directly.
2. **Provider-agnostic.** Model calls go through one interface; providers are swappable adapters.
3. **Prompts are data.** Personality and system prompts live in versioned files under `prompts/`.
4. **Measure everything.** Every change is checked against the eval set in `evals/`.
5. **Own the data.** Conversations are stored in our database, not the provider's.

## 3. Phase 1 scope
In scope:
- FastAPI backend with streaming `/chat`
- Provider layer: `ModelProvider` interface + one adapter (Anthropic)
- Personality prompt with `normal` and `brief` response modes
- Image input (vision)
- Conversation storage (SQLite)
- Web chat UI (React + Vite)
- Eval set + runner, token/cost logging
- Docker + deploy

Out of scope (later phases): backup provider adapter, tools/function calling (incl. code execution, web search), long-term memory, voice, wake word, context awareness, fine-tuning, glasses client, multi-user accounts, LLM-judged evals.

> v0.2 change (2026-09-30): backup provider adapter moved out of Phase 1. The provider interface stays, so a backup can be added later without touching the API layer.

## 4. Architecture

```
 [Web UI: React]  [future: phone / voice / glasses]
      \          |
       v         v
   +---------------------+
   |   mX API            |  FastAPI
   |  - auth (API key)   |
   |  - /chat (SSE)      |
   |  - prompt loader    |
   |  - logging / cost   |
   +----------+----------+
              |
     +--------v---------+        +-----------+
     |  Provider layer  |        |  SQLite   |
     |  base interface  |        | convos,   |
     |  + adapters      |        | messages, |
     +---+----------+---+        | images,   |
         |                       | usage     |
    Anthropic   [future: backup] +-----------+
```

Module layout:
- `api/main.py` — app, routes, dependencies (`require_key`, `get_db`, `get_provider`)
- `api/config.py` — settings (§10)
- `api/db.py` + `api/schema.sql` — SQLite access (§7)
- `api/prompts.py` — prompt loader (§8)
- `api/pricing.py` — per-model prices + cost function (§9)
- `providers/base.py`, `providers/errors.py`, `providers/anthropic_provider.py`

## 5. API (Phase 1)
All routes except `/health` require header `X-mX-Key`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check (public) |
| GET | `/whoami` | Auth check; temporary, removed once the web UI uses `/chat` |
| POST | `/chat` | Send a message; streams the reply (SSE) |
| GET | `/conversations` | List conversations, newest `updated_at` first, `?limit=50` |
| GET | `/conversations/{id}` | Conversation + its messages, oldest first; 404 if unknown |
| DELETE | `/conversations/{id}` | Delete conversation (cascades); 204, or 404 if unknown |
| GET | `/images/{id}` | Image bytes with its `Content-Type`; 404 if unknown (Week 3) |

### `POST /chat` request
```json
{
  "conversation_id": "optional-uuid",
  "message": "What's on this whiteboard?",
  "images": ["<base64>"],
  "mode": "normal"
}
```
- `conversation_id` omitted → a new conversation is created.
- `message`: 1–20,000 characters.
- `images` (Week 3): base64 only, max 4, max 5 MB each after decoding, types jpeg/png/gif/webp.
- `mode`: `"normal"` (default) or `"brief"`.
- Request bodies over ~25 MB are rejected (413).

### `POST /chat` response (SSE)
`StreamingResponse` with `Content-Type: text/event-stream`. Each event has a JSON `data` field:

| Event | Data | When |
|---|---|---|
| `meta` | `{conversation_id, message_id}` | First, before any text |
| `delta` | `{text}` | Each text chunk |
| `done` | `{usage: {model, input_tokens, output_tokens, cost_usd}}` | Reply finished and saved |
| `error` | `{code, message}` | Failure after streaming started; stream then ends |

Errors **before** streaming starts are normal JSON HTTP errors:
401 bad/missing key · 404 unknown `conversation_id` · 413 too large · 422 validation · 502/503 provider failure.

Clients must read the stream with `fetch` + a `ReadableStream` reader. The browser's `EventSource` can't send POST bodies or custom headers.

### Turn saving
A turn is **atomic**. The server generates the conversation and message IDs up front and sends them in `meta`. The conversation (if new), the user message, the assistant message and the usage row are written in **one transaction, only after the reply completes**. On a provider error or client disconnect nothing is saved, so history never contains half a turn.

### Conversation titles
The title is the first 60 characters of the first user message. No model call.

## 6. Provider interface
```python
class ModelProvider(Protocol):
    name: str
    async def generate(self, messages, system, **opts) -> ModelResponse: ...
    def stream(self, messages, system, **opts) -> AsyncIterator[str | ModelResponse]: ...
```
- `ModelResponse` has text, model name, and input/output token counts, so cost is logged the same way for every provider.
- `stream` is a plain `def` that returns an async iterator. It yields `str` chunks, and its **last item is a `ModelResponse`** with the full text and token counts. The Anthropic adapter gets this from the SDK's final message.
- Options: `max_tokens` is **4096** in normal mode and **150** in brief mode.
- Timeouts and retries use the SDK's built-in settings (`timeout=60s`, `max_retries=2`). No custom retry loop. Never retry once the first token has been sent.
- `providers/errors.py` defines `ProviderError` and its subclasses `ProviderAuthError`, `ProviderRateLimitError`, `ProviderUnavailableError` and `ProviderBadRequestError`. Adapters convert SDK exceptions into these. The API layer converts them into HTTP codes (before streaming) or an SSE `error` event (after).
- **History window:** only the last **20 messages** of a conversation are sent to the model. Only the current turn's images are sent; older images become the text `[image omitted]`.

## 7. Data model (SQLite)
Uses the standard-library `sqlite3` module with sync calls; no ORM and no migration tool.
- The schema lives in `api/schema.sql` and is applied at startup with `CREATE TABLE IF NOT EXISTS`. Its version is tracked with `PRAGMA user_version`.
- Every connection sets `PRAGMA foreign_keys=ON`, and the database runs in WAL mode.
- IDs are UUID4 text. Timestamps are ISO-8601 UTC text.
- The database file is at `DB_PATH` (default `./data/mx.db`). In Docker it goes on a `/data` volume.
- The connection comes from a FastAPI dependency, `get_db`, so tests can swap in a temporary database.

Tables:
- `conversations(id, title, created_at, updated_at)`
- `messages(id, conversation_id → conversations ON DELETE CASCADE, role, content, image_refs, created_at)`. `image_refs` is a JSON list of image IDs.
- `images(id, message_id → messages ON DELETE CASCADE, media_type, data BLOB, created_at)`. Images live inside the database, so there is one file to back up.
- `usage(id, message_id → messages ON DELETE CASCADE, provider, model, prompt_version, input_tokens, output_tokens, cost_usd, latency_ms, created_at)`

## 8. Personality and prompt loading
Defined in `prompts/mx_system_v1.md`.

mX is a broad expert and tutor: coding (many languages), math through calculus, science,
writing, planning/building projects, and inventing original ideas (innovation).
Tone is **formal and teacher-like**: explains step by step, shows reasoning, checks its work,
and helps Rio understand rather than only handing over answers. It stays honest about
uncertainty and its limits (no internet or code execution in Phase 1).

Modes:
- `normal`: full answers, markdown allowed
- `brief`: 1–2 sentences, no markdown (for voice and glasses later)

Loader (`api/prompts.py`):
- Reads the file named by `SYSTEM_PROMPT_FILE` and strips the `<!-- ... -->` header comment.
- Inserts the mode with `str.replace("{mode}", mode)`. It does **not** use `str.format`, which would break on `{}` in code examples.
- `mode` is validated as `Literal["normal", "brief"]`.
- The prompt version is the file name without extension (e.g. `mx_system_v1`). It is stored in `usage.prompt_version`.

## 9. Pricing and cost
`api/pricing.py` holds a dict `{model_id: (input_usd_per_million_tokens, output_usd_per_million_tokens)}`.
Rio fills it in from Anthropic's pricing page. Cost is `in_tokens × in_price / 1e6 + out_tokens × out_price / 1e6`.
For a model missing from the table, `cost_usd` is NULL and a warning is logged.

## 10. Config, security, and logging
Settings (`api/config.py`, loaded from `.env`):
`MX_API_KEY`, `ANTHROPIC_API_KEY`, `PRIMARY_PROVIDER`, `PRIMARY_MODEL`, `DB_PATH`, `SYSTEM_PROMPT_FILE`, `CORS_ORIGINS`.
`OPENAI_API_KEY` and `DATABASE_URL` are removed.

- **Auth:** the key is compared with `hmac.compare_digest` (constant-time). The app **refuses to start** if `MX_API_KEY` is empty, starts with `change-me`, or is shorter than 32 characters.
- **CORS:** `CORS_ORIGINS` defaults to `["http://localhost:5173"]` (the Vite dev server). The `X-mX-Key` and `Content-Type` headers are allowed.
- **Logging:** stdlib `logging`, one line per chat turn with conversation ID, model, tokens, cost, latency and status. **Never** log message content, images, or keys.

## 11. Testing
- `tests/conftest.py` sets a test `MX_API_KEY` and a temporary `DB_PATH`, so tests never depend on `.env`.
- `tests/fakes.py` has a `FakeProvider` that yields scripted chunks and a final `ModelResponse`, or raises a `ProviderError`. Routes get the provider through a `get_provider()` dependency, which tests override.
- Anthropic adapter tests mock the SDK.
- One real-API smoke test is marked `@pytest.mark.live` and is skipped when no `ANTHROPIC_API_KEY` is set.

## 12. Evals
- `evals/prompts.jsonl` has one object per line: `id`, `category`, `prompt`, optional `mode`, and `expect`.
- The runner (Week 4) calls the provider with the loaded prompt. It writes `evals/results/<date>_<prompt_version>.jsonl`, which git ignores.
- **Scoring:** `brief` prompts get automatic checks (at most 2 sentences, no markdown). Everything else is marked pass/fail by hand against `expect`. LLM-judged scoring is out of scope for Phase 1.

## 13. Decisions
Decided 2026-09-30:
- [x] **Provider:** Anthropic Claude API only for Phase 1. Backup provider deferred to a later phase (see §3).
- [x] **Name and tone:** mX. Formal, teacher-like broad expert (see §8).
- [x] **Web UI stack:** React + Vite, chosen so Rio can learn React. Needs Node.js, and CORS on the API (§10). JS vs. TypeScript to be decided at the start of Week 4.
- [x] **Deploy host:** deferred to Week 5. Constraint: host must offer a persistent disk for the SQLite file.
- [x] **Images:** stored as BLOBs in SQLite (§7).
- [x] **Failed/aborted turns:** save nothing (§5).
- [x] **History window:** last 20 messages; older images omitted (§6).
- [x] **`max_tokens`:** normal 4096, brief 150 (§6).
- [x] **Titles:** first 60 characters of the first user message (§5).
- [x] **Prompt loader and cost logging:** moved into Week 2.

## 14. Milestones
| Week | Deliverable |
|---|---|
| 1 | Repo, design doc, agent roles, API keys, `/health` running |
| 2 | Auth hardening, DB, Anthropic adapter, prompt loader, pricing, streaming `/chat`, conversation endpoints |
| 3 | Image input, prompt tuning against evals |
| 4 | React web UI, eval runner |
| 5 | Tests, Docker, deploy, Phase 1 review |
