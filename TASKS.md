# mX — Task list

## Week 1 — Foundation (~10 hrs)
- [x] Create repo structure (api/, providers/, prompts/, evals/, web/, tests/, docs/)
- [x] Draft design doc v0.1 (`docs/design.md`)
- [x] Define agent roles (`CLAUDE.md`, `.claude/agents/`)
- [x] `/health` endpoint + API-key check + tests
- [x] Create GitHub repo `ri12oe/mX` and push (15 min)
- [ ] Set up local env: `python -m venv .venv`, install, `pytest` passes (30 min)
- [ ] Get provider API key(s), put in `.env`, set a monthly spend limit (30 min)
- [ ] Decide open items in design.md §9: provider, assistant name, UI stack (1 hr)
- [ ] Review design.md with the architect agent and refine it (1–2 hrs)
- [ ] Write 10 starter eval prompts in `evals/prompts.jsonl` (1 hr)

## Week 2 — The brain (~12 hrs)
- [ ] Anthropic adapter implementing `ModelProvider` (generate + stream)
- [ ] Retries + timeout + error mapping in provider layer
- [ ] SQLite schema: conversations, messages, usage
- [ ] `POST /chat` with SSE streaming
- [ ] `GET/DELETE /conversations` endpoints
- [ ] Tests for all of the above (provider mocked)

## Week 3 — Personality & inputs
- [ ] Load system prompt from `prompts/`, add `normal` / `brief` modes
- [ ] Image input on `/chat`
- [ ] Second provider adapter

## Week 4 — Interface & quality
- [ ] Web chat UI
- [ ] Eval runner script (50 prompts)
- [ ] Token + cost logging

## Week 5 — Ship
- [ ] Test coverage pass
- [ ] Dockerfile + deploy
- [ ] Phase 1 review
