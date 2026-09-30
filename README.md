# mX

A personal AI assistant with its own backend, built on hosted model APIs.
Phase 1: brain, personality, and API layer. See `docs/design.md`.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then edit .env
pytest -q
uvicorn api.main:app --reload
```
Open http://127.0.0.1:8000/docs and try `/health`.
Test auth:
```bash
curl -H "X-mX-Key: <your key>" http://127.0.0.1:8000/whoami
```

## Layout
| Path | What |
|---|---|
| `docs/design.md` | Architecture and scope (source of truth) |
| `TASKS.md` | Task list, one task at a time |
| `CLAUDE.md`, `.claude/agents/` | Instructions and roles for AI coding agents |
| `api/` | FastAPI app |
| `providers/` | Model provider interface + adapters |
| `prompts/` | System prompts (versioned) |
| `evals/` | Eval prompts and results |
| `web/` | Chat UI (Week 4) |
| `tests/` | Pytest tests |
