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
- Docker + deploy → **changed in Week 5:** mX runs locally only; the Docker/Fly setup is kept but not deployed (§13)

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
- `api/main.py` — app setup, `/health`, `/whoami`
- `api/deps.py` — dependencies (`require_key`, `get_db`, `get_provider`)
- `api/chat.py` — `POST /chat`
- `api/conversations.py` — `GET /conversations`, `GET` and `DELETE /conversations/{id}`
- `api/config.py` — settings (§10)
- `api/db.py` + `api/schema.sql` — SQLite access (§7)
- `api/prompts.py` — prompt loader (§8)
- `api/pricing.py` — per-model prices + cost function (§9)
- `providers/base.py`, `providers/errors.py`, `providers/anthropic_provider.py`

## 5. API (Phase 1)
All routes except `/health` and `/auth/*` require **either** the `X-mX-Key` header (scripts, evals) **or** a valid session cookie from `POST /auth/login` (the web app). See §10.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | `{password}` → 204 + `mx_session` cookie; 401 wrong password; 429 after 5 failures (15 min) |
| POST | `/auth/logout` | 204, clears the cookie |

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check (public) |
| GET | `/whoami` | Auth check; temporary, removed once the web UI uses `/chat` |
| POST | `/chat` | Send a message; streams the reply (SSE) |
| GET | `/conversations` | List conversations, newest `updated_at` first, `?limit=50` |
| GET | `/conversations/{id}` | Conversation + its messages, oldest first; 404 if unknown |
| DELETE | `/conversations/{id}` | Delete conversation (cascades); 204, or 404 if unknown |
| GET | `/images/{id}` | Image bytes with its `Content-Type` (plus `X-Content-Type-Options: nosniff`, long private cache); 404 if unknown |

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
- `images`: base64 (or a `data:` URL), max 4, max 5 MB each after decoding, types jpeg/png/gif/webp. The type is read from the file's signature bytes, never from the client. Bad images get a 422 with `detail: {code: "invalid_image", message}` before the model is called. Images are stored with the turn (same transaction) and listed in the user message's `image_refs`.
- `mode`: `"normal"` (default) or `"brief"`.
- Request bodies over 30 MB are rejected (413). 4 images × 5 MB become ~26.7 MB as base64, so 25 MB was too small; 30 MB stays under the Claude API's 32 MB request limit.

### `POST /chat` response (SSE)
`StreamingResponse` with `Content-Type: text/event-stream`. Each event has a JSON `data` field:

| Event | Data | When |
|---|---|---|
| `meta` | `{conversation_id, message_id}` | First, before any text |
| `delta` | `{text}` | Each text chunk |
| `done` | `{usage: {model, input_tokens, output_tokens, cost_usd}, stop_reason}` | Reply finished and saved (`stop_reason: "max_tokens"` = reply was cut off) |
| `error` | `{code, message}` | Failure after streaming started; stream then ends |

Errors **before** streaming starts are normal JSON HTTP errors:
401 bad/missing key · 404 unknown `conversation_id` · 413 too large · 422 validation, a bad image (`invalid_image`), or the model declined (`provider_refused`) · 502 provider auth/bad request · 503 provider rate-limited or unavailable. Provider errors have `detail: {code, message}`. The route waits up to 10 s for the first chunk, so quick provider failures (bad key, overloaded, refused) become HTTP errors. If the model is still thinking after that, streaming starts anyway, and a `: ping` SSE comment is sent every 15 s while waiting, so proxies with idle timeouts (Fly.io: 60 s) keep the connection open. If the client disconnects, the pending model call is cancelled. After streaming starts, failures arrive as an `error` event, including `save_failed` if the database write fails.

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
- `ModelResponse` has text, the model that actually answered, input/output token counts, and `stop_reason` (`"max_tokens"` means the reply was cut off), so cost is logged the same way for every provider.
- `stream` is a plain `def` that returns an async iterator. It yields `str` chunks, and its **last item is a `ModelResponse`** with the full text and token counts. The Anthropic adapter gets this from the SDK's final message.
- **Per-mode settings** (`MODE_OPTIONS` in `api/prompts.py`; the `/chat` route passes these to the provider):

  | Mode | `max_tokens` | `effort` | Why |
  |---|---|---|---|
  | `normal` | 16000 | `high` | Hard math/coding/projects need careful reasoning; long answers must not be cut off |
  | `brief` | 2048 | `low` | Fast, short answers for voice/glasses; brevity comes from the prompt, the cap just leaves room for thinking |

  `max_tokens` is a ceiling, not a cost: only tokens used are billed. On Claude Opus 5.5 **thinking is always on** and its tokens count toward `max_tokens`, so caps must leave room for it. `effort` is sent as `output_config.effort`.
- **Refusals (Anthropic):** the model's safety classifiers can decline a request, returned as a normal reply with `stop_reason: "refusal"`. The adapter opts into server-side fallbacks (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`), so some declines are retried on another model automatically. A decline that isn't rescued raises `ProviderRefusalError` (with its category).
- HTTP status mapping (Anthropic): 401/403 → auth · 402/429 → rate limit (incl. billing/spend limit) · 408/409/5xx/529 and network errors → unavailable · other 4xx (incl. 404 unknown model) → bad request.
- Timeouts and retries use the SDK's built-in settings: connect timeout 10 s, read timeout 10 min (a long reasoned reply can take minutes; a shorter timeout would cut it off and the retry would bill it again), `max_retries=2`. No custom retry loop. Never retry once the first token has been sent.
- `providers/errors.py` defines `ProviderError` and its subclasses `ProviderAuthError`, `ProviderRateLimitError`, `ProviderUnavailableError`, `ProviderBadRequestError`, `ProviderRefusalError` and `UnknownProviderError`. Adapters convert SDK exceptions into these. The API layer converts them into HTTP codes (before streaming) or an SSE `error` event (after).
- **History window:** at most **20 messages** are sent to the model: the last 19 stored plus the new one, trimmed so the history always starts with a user message. Only the current turn's images are sent (as image blocks before the text); each older image becomes a line `[image omitted]` above that message's text.

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
Defined in `prompts/mx_system_v3.md` (tuned in Week 3; see `evals/tuning-log.md`). Earlier versions stay in `prompts/` for comparison.

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
Filled in 2026-09-30 for Opus 5.5 plus the Opus/Sonnet models that refusal fallbacks can route to; verify against Anthropic's pricing page when adding or changing a model. Cost is `in_tokens × in_price / 1e6 + out_tokens × out_price / 1e6`.
For a model missing from the table, `cost_usd` is NULL and a warning is logged.

## 10. Config, security, and logging
Settings (`api/config.py`, loaded from `.env`):
`MX_API_KEY`, `ANTHROPIC_API_KEY`, `PRIMARY_PROVIDER`, `PRIMARY_MODEL`, `DB_PATH`, `SYSTEM_PROMPT_FILE`, `CORS_ORIGINS`.
`OPENAI_API_KEY` and `DATABASE_URL` are removed.

- **Auth:** the key is compared with `hmac.compare_digest` (constant-time). The app **refuses to start** if `MX_API_KEY` is empty, starts with `change-me`, or is shorter than 32 characters.
- **Web login (Week 5):** `MX_PASSWORD` (≥ 12 chars, required) → `POST /auth/login` sets `mx_session`, an **HttpOnly, Secure, SameSite=Strict** cookie valid 30 days. The token is `<expiry>.<HMAC-SHA256(MX_API_KEY, expiry)>`: stateless, and changing `MX_API_KEY` signs every device out. 5 wrong passwords in 15 min lock logins for 15 min (in memory; the key still works). No key or password is stored in the browser.
- **Same origin:** in production the API serves the built web app at `/` (`WEB_DIST`); in development Vite proxies API paths to uvicorn. CORS is only for other origins.
- **Security headers** on every response: a strict `Content-Security-Policy` (scripts only from the site; `unsafe-inline` styles for KaTeX; skipped on `/docs` and `/redoc`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- **CORS:** `CORS_ORIGINS` defaults to `["http://localhost:5173"]` (the Vite dev server). The `X-mX-Key` and `Content-Type` headers are allowed.
- **Logging:** stdlib `logging`, one line per chat turn with conversation ID, model, tokens, cost, latency and status. **Never** log message content, images, or keys.

## 11. Testing
- `tests/conftest.py` sets a test `MX_API_KEY` and a temporary `DB_PATH`, so tests never depend on `.env`.
- `tests/fakes.py` has a `FakeProvider` that yields scripted chunks and a final `ModelResponse`, or raises a `ProviderError`. Routes get the provider through a `get_provider()` dependency, which tests override.
- Anthropic adapter tests mock the SDK.
- One real-API smoke test is marked `@pytest.mark.live`. Live tests are **opt-in** (`pytest -m live`) so a normal `pytest` run never spends money; `pytest.ini` deselects them by default. They're also skipped when no `ANTHROPIC_API_KEY` is set.

## 12. Evals
- `evals/prompts.jsonl` has one object per line: `id`, `category`, `prompt`, optional `mode`, and `expect`.
- The runner (Week 4) calls the provider with the loaded prompt. It writes `evals/results/<date>_<prompt_version>.jsonl`, which git ignores.
- **Scoring:** `brief` prompts get automatic checks (at most 2 sentences, no markdown). Everything else is marked pass/fail by hand against `expect`. LLM-judged scoring is out of scope for Phase 1.

## 13. Decisions
Decided 2026-09-30:
- [x] **Provider:** Anthropic Claude API only for Phase 1. Backup provider deferred to a later phase (see §3).
- [x] **Name and tone:** mX. Formal, teacher-like broad expert (see §8).
- [x] **Web UI stack:** React + Vite, chosen so Rio can learn React. Needs Node.js, and CORS on the API (§10). **TypeScript** (decided 2026-09-30, Week 4): matches the typed Python side and catches mistakes while learning. Replies render markdown, code highlighting, and KaTeX math; the API key is stored in the browser's localStorage (acceptable for a personal local app; revisit before deploy). See `web/README.md`.
- [x] **Deploy host: Fly.io** (decided 2026-09-30, Week 5, after a researcher comparison of Fly.io, Railway, Render, and a VPS): about $2/month with a 1 GB volume, HTTPS on `*.fly.dev`, and no total streaming cap as long as bytes flow (hence heartbeats). One machine only (SQLite). Guide: `docs/deploy.md`.
- [x] **Web login: password + HttpOnly session cookie** (decided 2026-09-30, Week 5), replacing the API key in localStorage (§10).
- [x] **Run locally only; don't publish** (decided 2026-09-30, Week 5). mX runs on Rio's laptop via `start-mx.ps1`: uvicorn on `127.0.0.1:8000` serving the built web app, so only this computer can reach it. No hosting cost. The Dockerfile, `fly.toml`, and `docs/deploy.md` stay in the repo in case this changes. For phone access later, use a private network such as Tailscale rather than exposing the server; plain HTTP on the LAN would send the password unencrypted, and the Secure cookie wouldn't work.
- [x] **Images:** stored as BLOBs in SQLite (§7).
- [x] **Failed/aborted turns:** save nothing (§5).
- [x] **History window:** last 20 messages; older images omitted (§6).
- [x] **Model:** Claude Opus 5.5 (`claude-opus-5-5`, $4 / $20 per MTok) for the strongest math, coding, and invention. Changed from Sonnet 5.5 on 2026-09-30.
- [x] **`max_tokens` and effort:** normal 16000 / `high`, brief 2048 / `low` (§6). Replaces normal 4096 / brief 150, which thinking tokens could exhaust.
- [x] **Refusal fallbacks:** on (`fallbacks: "default"`, §6).
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
