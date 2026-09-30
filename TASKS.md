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
- [ ] 9. `GET /conversations`, `GET /conversations/{id}`, `DELETE /conversations/{id}` with cascade and 404s; tests (§5) (1–2 h)

## Week 3 — Personality & inputs
- [ ] Image input on `/chat` (base64, limits, stored in `images`) + `GET /images/{id}` (§5, §7)
- [ ] Tune `prompts/mx_system_v1.md` against the eval set; grow evals toward 50

## Week 4 — Interface & quality
- [ ] Install Node.js, scaffold React + Vite app in `web/` (decide JS vs. TypeScript)
- [ ] React chat UI with streaming replies (`fetch` + stream reader, §5)
- [ ] Eval runner script (50 prompts, auto-checks for `brief`, §12)

## Week 5 — Ship
- [ ] Test coverage pass
- [ ] Dockerfile (DB on a `/data` volume) + deploy
- [ ] Phase 1 review
