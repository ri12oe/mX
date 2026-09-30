# mX

A personal AI assistant with its own backend, built on hosted model APIs.
Phase 1: brain, personality, and API layer. See `docs/design.md`.

## Run mX
Double-click **`start-mx.cmd`**, or run `.\start-mx.ps1` in PowerShell. It:
1. checks your venv and `.env` (you need `MX_API_KEY`, `MX_PASSWORD`, and `ANTHROPIC_API_KEY`);
2. installs web dependencies the first time, and rebuilds the web app only when its files changed;
3. starts mX on http://localhost:8000 and opens it in your browser. Sign in with `MX_PASSWORD`.

Only this computer can reach it (`127.0.0.1`). Press **Ctrl+C** in the window to stop mX.
If it's already running, the script just opens the browser.

**Back up your chats.** They live in `data/mx.db`, which isn't in git. Copy that file somewhere safe now and then
(stop mX first, or copy `mx.db`, `mx.db-wal`, and `mx.db-shm` together).

mX isn't published online. `Dockerfile`, `fly.toml`, and `docs/deploy.md` are kept in case that changes.

## Development setup
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env             # then edit .env
pytest -q
uvicorn api.main:app --reload
```
Open http://127.0.0.1:8000/docs and try `/health`.
Test auth:
```bash
curl -H "X-mX-Key: <your key>" http://127.0.0.1:8000/whoami
```
Chat with mX in the terminal (real API calls, costs money; add `brief` for cheaper replies):
```bash
python try_mx.py
```
Real-API smoke test (opt-in, about $0.0002): `pytest -m live -s`

Coverage: `pytest --cov` (settings in `.coveragerc`) and `npm run coverage` in `web/`.

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
