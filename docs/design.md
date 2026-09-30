# Jarvis — Design Doc (v0.1, Phase 1)

Owner: Rio · Status: Draft · Last updated: 2026-09-30

## 1. Goal
A personal AI assistant ("Jarvis") that Rio can chat with through his **own backend**,
built on hosted model APIs. Phase 1 delivers the brain, personality, and API layer.
Later phases add tools, memory, voice, context awareness, and AR-glasses clients.

## 2. Principles
1. **Backend-first.** Every client (web, phone, voice, glasses) talks to the Jarvis API, never to a model provider directly.
2. **Provider-agnostic.** Model calls go through one interface; providers are swappable adapters.
3. **Prompts are data.** Personality and system prompts live in versioned files under `prompts/`.
4. **Measure everything.** Every change is checked against the eval set in `evals/`.
5. **Own the data.** Conversations are stored in our database, not the provider's.

## 3. Phase 1 scope
In scope:
- FastAPI backend with streaming `/chat`
- Provider layer with 2 adapters (primary + one backup)
- Personality prompt with `normal` and `brief` response modes
- Image input (vision)
- Conversation storage (SQLite)
- Simple web chat UI
- Eval set + runner, token/cost logging
- Docker + deploy

Out of scope (later phases): tools/function calling, long-term memory, voice, wake word, context awareness, fine-tuning, glasses client, multi-user accounts.

## 4. Architecture

```
 [Web UI]  [future: phone / voice / glasses]
      \          |
       v         v
   +---------------------+
   |   Jarvis API        |  FastAPI
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
     +---+----------+---+        | usage     |
         |          |            +-----------+
    Provider A  Provider B
```

## 5. API (Phase 1)
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/chat` | Send a message; streams the reply (SSE) |
| GET | `/conversations` | List conversations |
| GET | `/conversations/{id}` | Get messages in a conversation |
| DELETE | `/conversations/{id}` | Delete a conversation |

`POST /chat` request:
```json
{
  "conversation_id": "optional-uuid",
  "message": "What's on this whiteboard?",
  "images": ["<base64 or upload id>"],
  "mode": "normal"
}
```
All requests require header `X-Jarvis-Key`.

## 6. Provider interface
```python
class ModelProvider(Protocol):
    name: str
    async def generate(self, messages, system, **opts) -> ModelResponse: ...
    async def stream(self, messages, system, **opts) -> AsyncIterator[str]: ...
```
`ModelResponse` includes text, input/output token counts, and model name, so cost can be logged uniformly.

## 7. Data model (SQLite)
- `conversations(id, title, created_at, updated_at)`
- `messages(id, conversation_id, role, content, image_refs, created_at)`
- `usage(id, message_id, provider, model, input_tokens, output_tokens, cost_usd, latency_ms)`

## 8. Personality
Defined in `prompts/jarvis_system_v1.md`. Modes:
- `normal` — full answers, markdown allowed
- `brief` — 1–2 sentences, no markdown (for voice and glasses later)

## 9. Open decisions
- [ ] Primary provider (default assumption: Anthropic Claude API) and backup provider
- [ ] Assistant name and voice/tone
- [ ] Web UI stack (plain HTML/JS vs. React)
- [ ] Deploy host

## 10. Milestones
| Week | Deliverable |
|---|---|
| 1 | Repo, design doc, agent roles, API keys, `/health` running |
| 2 | Provider layer + streaming `/chat` + SQLite history |
| 3 | Personality, modes, image input, second adapter |
| 4 | Web UI, eval set, cost logging |
| 5 | Tests, Docker, deploy, Phase 1 review |
