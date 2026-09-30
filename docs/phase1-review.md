# mX Phase 1 review

2026-09-30 · Reviewer: independent `reviewer` agent (read-only), with fixes applied in the same PR.

## Verdict
**Phase 1 is complete**, measured against `docs/design.md` including the scope changes recorded in its §13. mX is a
working personal AI tutor. It streams answers from Claude Opus 5.5 into a React web app, remembers conversations in
SQLite, accepts images, tracks the cost of every reply, and is guarded by a password login. It runs locally on
Rio's laptop via `start-mx.cmd`. The review found **no critical issues** and one high-severity UI bug, which was
fixed and tested here (see below).

## What Phase 1 promised vs. delivered
| Design §3 scope | Status | Where |
|---|---|---|
| FastAPI backend with streaming `/chat` | ✅ SSE `meta`/`delta`/`done`/`error`, heartbeats, fail-fast errors, all-or-nothing saves | `api/chat.py` |
| Provider layer | ✅ `ModelProvider` interface, Anthropic adapter, refusal fallbacks, error mapping. **Changed:** one adapter; the backup was deferred (Week 1) | `providers/` |
| Personality with `normal` / `brief` modes | ✅ Tuned v1 → v3 against evals; per-mode `max_tokens` and effort | `prompts/mx_system_v3.md`, `api/prompts.py` |
| Image input (vision) | ✅ Up to 4 images, type checked from the file bytes, stored with the turn | `api/images.py` |
| Conversation storage (SQLite) | ✅ 4 tables, cascade deletes, atomic turns | `api/db.py`, `api/schema.sql` |
| Web chat UI | ✅ React 19 + Vite + TypeScript: streaming, Stop, images, KaTeX math, light/dark, phone width | `web/` |
| Eval set + runner, token/cost logging | ✅ 50 prompts, runner with a spend cap, cost per reply, tuning log | `evals/`, `api/pricing.py` |
| Docker + deploy | **Changed (Week 5):** Docker and Fly.io setup built and kept, but **mX runs locally only** by choice | `Dockerfile`, `fly.toml`, `start-mx.ps1` |

**Added beyond the original scope:** a password login with an HttpOnly session cookie, brute-force lockout, security
headers (CSP), heartbeats for long replies, and a one-click local launcher.

## By the numbers
| | |
|---|---|
| Merged PRs | 23 (one task per PR) |
| Code | ~1,100 lines backend, ~220 eval runner, ~1,570 web app, ~370 CSS |
| Tests | **237 Python** (99% coverage, 0 missed lines) · **65 web** (96% of lines) |
| Evals | 50 prompts, 16 categories; v3 scores **47/50** (tuning log: `evals/tuning-log.md`) |
| Model | Claude Opus 5.5 (`claude-opus-5-5`), about $0.016 per typical normal-mode reply |
| Claude spend during development | About $2.60, mostly the prompt-tuning runs (my test calls, not counting Rio's own use) |

## How the plan changed (all recorded in design.md §13)
1. **Jarvis → mX** (Week 1).
2. **Anthropic only**; the backup provider was deferred (Week 1).
3. **Formal, teacher-like expert** personality, later extended with an Innovation skill (Weeks 1–3).
4. **Sonnet 5.5 → Opus 5.5**, with `max_tokens` and effort per mode (Week 2). The model always thinks, so small token limits would have cut answers off.
5. **Heartbeats and a 10-minute read timeout**, because long reasoned replies can take minutes (Weeks 2 and 5).
6. **The eval runner moved from Week 4 to Week 3**, since tuning needs a way to measure.
7. **TypeScript** for the web app (Week 4).
8. **Password + cookie login** instead of an API key stored in the browser (Week 5).
9. **Local only**: Fly.io was chosen and set up, then publishing was declined (Week 5).

## Review findings and what happened to them
| # | Severity | Finding | Outcome |
|---|---|---|---|
| 1 | **High** | After a failed or stopped *first* turn, the app kept the unsaved conversation ID, so every retry got a 404 until "New chat" | **Fixed.** The ID is adopted only on `done`. 2 regression tests (fail, then retry; stop, then retry) |
| 2 | Medium | `fastapi>=0.115` allowed 0.106–0.117, which close the DB connection before a streamed reply is saved | **Fixed.** Pinned `fastapi>=0.118`; `test_works_with_the_real_db_dependency` also guards this |
| 3 | Medium | The design doc had drifted (`/whoami` "temporary", a stale localStorage note, missing settings and modules) | **Fixed** |
| 4 | Low | An unexpected (non-provider) exception cut the stream off silently | **Fixed.** The server logs a traceback and sends `internal_error`; the client reports a stream that ends without `done`/`error`. Tests on both sides |
| 5 | Low | `/chat` runs sync SQLite reads/writes and base64 decoding on the event loop | **Deferred.** Harmless for one local user; move to a worker thread if mX gets more users |
| 6 | Low | The 30 MB limit trusts `Content-Length`, so a chunked upload isn't capped | **Deferred.** Local-only, and bound to `127.0.0.1` |
| 7 | Low | Logout can't revoke a copied cookie (stateless sessions) | **Documented.** Changing `MX_API_KEY` signs every device out (README) |
| 8 | Low | `try_mx.py` described itself as a temporary helper | **Relabeled** as a terminal tool for prompt experiments; README updated |
| 9 | Low | CORS is configured but unused | **Documented** as unused in design §10; kept for a future client |
| — | Nits | web README pointed at Docker for normal use; the start script didn't check the key length | **Fixed** |

**Security checks that passed:**
- No secrets anywhere in git history, and no message content in logs.
- Cookie flags and HMAC signing.
- CSRF blocked by SameSite=Strict plus JSON bodies.
- Login lockout, the CSP, and no raw HTML in rendered markdown.
- Parameterized SQL only; static-file path traversal handled; bound to `127.0.0.1`.
- Provider SDK used only in `providers/`, and no hardcoded prompts.

## Phase 2: recommended order
1. **Tools: sandboxed code execution first, then web search.** mX currently has to admit it can't run code or look things up. Checking math and code by actually running it is the biggest accuracy gain for a tutor.
2. **Long-term memory:** a small "learner profile" (topics studied, recurring mistakes, preferences) added to the prompt, so mX teaches Rio over time instead of starting every chat cold.
3. **Prompt caching and a cost view** built from the `usage` table. Opus replies with long thinking add up; caching the system prompt and history cuts input cost with very little code.
4. **A v4 prompt round:** the two known misses in the tuning log (long comparison answers, p31/p40; hedged guesses about images, p33). Cheap, and the runner is ready.
5. **Phone access through Tailscale**, then voice via `brief` mode, as a step toward the glasses client. It reuses the current app without making it public.
