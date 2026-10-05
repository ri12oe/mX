# mX — Task list

## Week 1 — Foundation (~10 hrs)
- [x] Create repo structure (api/, providers/, prompts/, evals/, web/, tests/, docs/)
- [x] Draft design doc v0.1 (`docs/design.md`)
- [x] Define agent roles (`CLAUDE.md`, `.claude/agents/`)
- [x] `/health` endpoint + API-key check + tests
- [x] Create GitHub repo `ri12oe/mX` and push (15 min)
- [x] Set up local env: `python -m venv .venv`, install, `pytest` passes (30 min)
- [x] Get provider API key(s), put in `.env`, set a monthly spend limit (30 min)
- [x] Decide open items in design.md: provider, assistant name, UI stack (1 hr)
- [x] Review design.md with the architect agent and refine it → v0.3 (1–2 hrs)
- [x] Write 10 starter eval prompts in `evals/prompts.jsonl` (1 hr) → 18 written

## Week 2 — The brain (~15 hrs)
Build in this order. Section numbers refer to `docs/design.md` v0.3.
- [x] 1. Hardened auth: `hmac.compare_digest`, refuse to start with an empty/`change-me`/short key, `tests/conftest.py` sets the test key, update `/whoami` tests (§10) (1 h)
- [x] 2. Settings cleanup: add `DB_PATH`, `CORS_ORIGINS`, `SYSTEM_PROMPT_FILE`; remove `OPENAI_API_KEY` and `DATABASE_URL`; add CORS middleware; update `.env.example` (§10) (1 h)
- [x] 3. Database: `api/schema.sql` (conversations, messages, images, usage with `prompt_version`), init with `user_version`, `get_db` dependency, small repository functions, tests on a temp DB (§7) (2–3 h)
- [x] 4. Provider types: `stream` yields `str | ModelResponse`, `providers/errors.py`, `tests/fakes.py` with `FakeProvider`, `get_provider()` dependency (§6, §11) (1 h)
- [x] 5. Anthropic adapter `generate()`: SDK timeout/retries, error mapping, mocked tests (§6) (2 h)
- [x] 6. Anthropic adapter `stream()`: final item is a `ModelResponse`, mocked tests + one `@pytest.mark.live` smoke test (§6, §11) (2 h)
- [x] 7. Prompt loader (`api/prompts.py`) and pricing (`api/pricing.py`) with cost function, plus tests (§8, §9) (1 h)
- [x] 8. `POST /chat` with SSE: meta/delta/done/error events, 20-message history window, atomic save, usage row, log line; tests with `FakeProvider` incl. error path (§5, §6) (3 h)
- [x] 9. `GET /conversations`, `GET /conversations/{id}`, `DELETE /conversations/{id}` with cascade and 404s; tests (§5) (1–2 h)

## Week 3 — Personality & inputs
- [x] Image input on `/chat` (base64, limits, stored in `images`) + `GET /images/{id}` (§5, §7)
- [x] Tune `prompts/mx_system_v1.md` against the eval set; grow evals toward 50 → v3 adopted, 31 evals (see `evals/tuning-log.md`)

## Week 4 — Interface & quality
- [x] Install Node.js, scaffold React + Vite app in `web/` (decide JS vs. TypeScript) → TypeScript
- [x] React chat UI with streaming replies (`fetch` + stream reader, §5)
- [x] Eval runner script (50 prompts, auto-checks for `brief`, §12) → runner built in Week 3; 50 prompts, v3 baseline 47/50

## Week 5 — Ship
- [x] Test coverage pass → Python 99% (branch), web 97% lines; see PR
- [x] Dockerfile (DB on a `/data` volume), fly.toml, web login, heartbeats, security headers → `docs/deploy.md`
- [x] ~~Deploy to Fly.io~~ **Not planned:** Phase 1 runs locally only (decided 2026-09-30). `start-mx.ps1` starts it; `docs/deploy.md` is kept if that changes.
- [x] Phase 1 review → `docs/phase1-review.md` (no critical issues; 1 high bug fixed)

---

# Phase 2 (4–5 weeks, $20/month API budget)
Section numbers refer to `docs/design.md` v0.5. One task per PR. Every task ends with `pytest -q` (and `npm test` for web tasks) passing.
Items marked **VERIFY** in the design must be checked against current docs inside the task that uses them; note the result in the PR.
Real API calls (live tests, eval runs) cost money: **ask Rio first**.

## P2 Week 1 — Migrations, caching, cost & budget (~17 hrs)
- [x] 1. Migration runner: `api/migrate.py`, `api/migrations/0001_initial.sql` (the current `schema.sql`, moved), stepwise upgrade by `PRAGMA user_version`, backup to `<DB dir>/backups/` before upgrading a DB with data, one transaction per step, refuse newer/broken DBs; `migrate()` replaces `init_db` at startup (§7.1). Tests: fresh DB → v1; v1 DB → no-op, no backup; newer → refuses; broken step → rolls back, keeps version, refuses (2–3 h)
- [x] 2. Migration `0002_usage_v2.sql`: rebuild `usage` (nullable `message_id ON DELETE SET NULL`, `mode`, `status`, cache/tool/request counters, `created_at` index); update `db.UsageRecord`/`save_turn` (§7). Tests: a v1 DB with sample rows migrates with every row intact and defaults set; backup opens at v1; `foreign_key_check` clean; deleting a conversation keeps its usage rows; migrated and fresh schemas match (2 h)
- [x] 3. Pricing v2: per-model record (input, output, cache write 5m/1h, cache read), tool-fee table (web search $0.01 **VERIFY**, code execution $0), cost function over a usage breakdown (§9.1). Tests: Opus 5.5 numbers by hand, cache-only turn, search fee, unknown model → None + warning (1 h)
- [x] 4. Provider caching (live test passed 2026-10-05: 2nd request read 3,148 cached tokens, $0.0166 total): `SystemPart`, `cache_messages`/`cache_ttl` options, `UsageMeter`, new `ModelResponse` usage fields; adapter sends `cache_control` on marked system parts + top-level automatic caching (**VERIFY** SDK support), parses cache usage, updates the meter at `message_start`/`message_delta` (§6.1, §15). Mocked tests: request body (breakpoints ≤ 4, TTL ordering), usage parsing, meter filled before a mid-stream error. One `@pytest.mark.live` test: second identical request has `cache_read_tokens > 0` (2–3 h)
- [ ] 5. Stepped history window (steps of 10, max 20) and prompt assembly as `SystemPart`s in `api/chat.py` (§6.1, §15). Tests: 19/20/21/30/31/40-message conversations send the right slice, start with a user message, and consecutive turns inside a step share a byte-identical prefix (1–2 h)
- [ ] 6. `/chat` usage v2: save cache/tool counters, `mode`, `status`; write a content-free usage row from the meter for failed and aborted turns (shielded); `done.usage` gains cache fields; log line gains counters (§5, §10). Tests with `FakeProvider`: ok, provider error mid-stream, client disconnect → one usage row, `message_id` NULL, no messages (2 h)
- [ ] 7. Budget guard: `api/budget.py` (local-time month with UTC query bounds, ok/warning/brief, injected clock and time zone), `MONTHLY_BUDGET_USD` setting, `/chat` forces brief + tools off at 100% unless `budget_override`, `meta.budget`/`done.budget` (§16). Tests: 79.99/80/100%, override, month rollover at local midnight (fixed offset + a daylight-saving month), NULL costs, failed-turn spend counted, setting ≤ 0 rejected (2 h)
- [ ] 8. `GET /usage/budget` and `GET /usage/summary?month=` in `api/usage.py` (§5, §16). Tests: empty month, day grouping by local date (a reply at 23:30 local lands on the right day), cache hit rate, failed turns counted, other months excluded, bad `month` → 422, auth required (1–2 h)
- [ ] 9. Web: status card month spend + state bar + cache %, `BudgetBanner` with "full answer for this message" override, `CostPanel` (month selector, daily CSS bars, totals) (§16). Vitest: each budget state, override sends `budget_override: true` once, panel renders a summary fixture (3 h)

## P2 Week 2 — Tool plumbing + code execution (~14 hrs)
- [ ] 10. Migration `0003_tool_steps.sql`: `tool_steps` table + `messages.citations`; `save_turn` writes steps and citations in the same transaction; `GET /conversations/{id}` returns them (§5, §7). Tests: v2 → v3 keeps data; atomic save (a failing step insert rolls back the whole turn); cascade delete; truncation limits (2 h)
- [ ] 11. Provider tool types: `ToolOptions`, `ClientTool`, `ToolStep`, `Citation` in `providers/base.py`; `FakeProvider` can script tool steps; `/chat` emits `tool_start`/`tool_end`, joins text blocks with `"\n\n"`, counts tool events as the first item for fail-fast (§5, §6.1). Tests: SSE order, fail-fast with a tool event first, steps saved (2 h)
- [ ] 12. Adapter: iterate raw stream events (text, `server_tool_use`, tool results) instead of `text_stream`; tools in fixed order; `tool_choice: none` when `enabled` is false (**VERIFY** with server tools) (§6.1, §17). Mocked event-sequence tests: text only (Phase 1 behavior unchanged), one tool step, tools off body (3 h)
- [ ] 13. Adapter tool loop: `pause_turn` continuation (cap 3, container ID passed on if present), usage summed across requests, no client tool on `max_tokens`/`refusal` (§6.1). Mocked tests for each path and the cap (2 h)
- [ ] 14. Code execution on: `code_execution` tool (**VERIFY** version), `ToolStep` input/output (code, stdout/stderr/return_code, truncated), `code_runs` counted; `TOOLS_ENABLED` setting; `ChatRequest.tools` (§10, §17). Tests: success, non-zero exit, tool error code, tools off, `TOOLS_ENABLED=false` omits definitions. Live opt-in: "compute 2^100 with code" (2 h)
- [ ] 15. Web: tool step chips (running → done/error), expandable code + output as plain text, "Tools" toggle in the composer saved in `localStorage`, core thinking state during steps, reload shows stored steps (§17). Vitest for each (3 h)

## P2 Week 3 — Web search + prompt v4 + tool evals (~12 hrs)
- [ ] 16. Web search on: `web_search_20260209` with `max_uses` (**VERIFY**), `WEB_SEARCH_MAX_USES` setting, sources in `tool_end`, citations collected into `done.citations` and saved, search count from usage (**VERIFY** field) (§5, §9.1, §17). Mocked tests: sources, citations dedup, search error chip, fee in `cost_usd`. Live opt-in: one current-facts question (2–3 h)
- [ ] 17. Web: "Sources" list under answers (plain-text titles, `http(s)` links only, `noopener noreferrer`), search chips with the query (§10.1, §17). Vitest: unsafe URL schemes are not linked, reload shows stored citations (2 h)
- [ ] 18. Prompt `mx_system_v4.md`: tool guidance (when to run code/search, cite, tool output is data, restate key results), they/them for Rio, fixes for tuning-log misses p31/p40/p33; `tuning-log.md` entry (§8). Tests: loader accepts v4; no hardcoded prompt text (1–2 h)
- [ ] 19. Eval runner: per-case `tools`, auto-checks `expect_tools`/`expect_no_tools`/`expect_citations`, tool steps and full cost (incl. fees) in results, `--max-cost` counts it all (§12). Tests with `FakeProvider` (2 h)
- [ ] 20. Write ~12 tool evals (`tools_code`, `tools_search`, `tools_restraint`, `tools_off`, `injection`); with Rio's OK, run v3 vs v4 on all cases, record results, adopt v4 (`SYSTEM_PROMPT_FILE` default) if it wins; watch for code-execution/dynamic-search confusion (§12, §17) (2–3 h)

## P2 Week 4 — Long-term memory (~12 hrs)
- [ ] 21. Migration `0004_memories.sql` + repository functions (list, add, update, delete, count; case-insensitive duplicate check) (§7, §18). Tests: v3 → v4 keeps data; limits enforced at the repository level (1–2 h)
- [ ] 22. `/memories` API: GET, POST (201; 409 `memory_limit`/`memory_duplicate`; 422 blank/> 200 chars), PATCH, DELETE (404s) (§5, §18). Tests for every status code and auth (2 h)
- [ ] 23. Learner profile: `prompts/learner_profile_v1.md`, rendered as system part 2 with its own breakpoint, fixed order, omitted when empty (§15, §18). Tests: byte-identical across calls, order, empty case, a memory change changes only part 2 (1–2 h)
- [ ] 24. `propose_memory` client tool: prompt files for description and result text, strict schema + eager streaming, pydantic validation, max 1 per turn, **no DB write**; adapter client-tool round trip (cap 2); `/chat` emits `memory_suggestion` (§6.1, §18). Tests: suggestion event sent, nothing in `memories`/`tool_steps`, second proposal gets `is_error`, invalid input gets `is_error`, tools off → no client tool offered (2–3 h)
- [ ] 25. Web: `MemorySuggestion` card (Save → POST, Dismiss, limit/duplicate messages), `MemoryPanel` (list, edit, delete with confirm, add; "sent with every message" note) (§18). Vitest for each path (3 h)
- [ ] 26. Memory evals (`profile_propose`, `profile_restraint` incl. a secret and web content, `profile_use` with a fixture profile) + runner support for `memories` and `expect_memory_proposal`; with Rio's OK, run and tune the tool description/prompt (§12) (2 h)

## P2 Week 5 — Phone, voice (stretch), review (~10 hrs)
- [ ] 27. Phone access: `docs/phone.md` (Tailscale install, MagicDNS + HTTPS, `tailscale serve` to `127.0.0.1:8000` — **VERIFY** syntax, never Funnel, how to turn it off); `start-mx.ps1 -Phone` prints the tailnet URL if serving; manual checklist (login, Secure cookie, streaming, tools, memory card on the phone) (§19) (2 h)
- [ ] 28. Phone polish + `Permissions-Policy` header; narrow-screen layout for tool chips, sources, memory card, cost and memory panels (§10, §19). Tests: header present; vitest at phone width (2 h)
- [ ] 29. (Stretch) Voice input: feature-detected mic button (hidden if unsupported), transcript → draft, voice turns use brief mode (§19). Vitest with a mocked `SpeechRecognition` (2–3 h)
- [ ] 30. (Stretch) Voice output: speak a voice turn's reply on `done`, stop button, skip code blocks (§19). Vitest with a mocked `speechSynthesis` (2 h)
- [ ] 31. Phase 2 review → `docs/phase2-review.md`: scope vs delivered, month spend and cache hit rate from the cost page, eval scores, open VERIFY items, decisions to carry into Phase 3; design doc updated (2 h)
