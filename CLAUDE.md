# Jarvis — instructions for AI coding agents

Read these before doing anything:
1. `docs/design.md` — the architecture and scope. It is the source of truth.
2. `TASKS.md` — the current task list. Work on ONE task at a time.

## Rules
- Stay inside Phase 1 scope (design.md §3). If a task needs something out of scope, stop and say so.
- Python 3.11, FastAPI, type hints everywhere, small functions.
- Never call a model provider SDK outside `providers/`. The API layer only uses the `ModelProvider` interface.
- Prompts live in `prompts/` as files, never hardcoded strings.
- Never commit secrets. Config comes from `api/config.py` / `.env`.
- Every new endpoint or provider method gets a test in `tests/`.
- Run `pytest` before saying a task is done.
- If the design doc and a request disagree, point it out instead of guessing.

## Commands
- Install: `pip install -r requirements.txt`
- Run: `uvicorn api.main:app --reload`
- Test: `pytest -q`
