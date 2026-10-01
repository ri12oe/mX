# mX web UI

React 19 + Vite + TypeScript chat UI for the mX API (docs/design.md §5, §13).

## Run it
You need two terminals, both started from the project root.

1. Start the API (with the Python venv active):
   ```bash
   uvicorn api.main:app --reload
   ```
2. Start the web app:
   ```bash
   cd web
   npm install      # first time only
   npm run dev
   ```
3. Open http://localhost:5173 and sign in with `MX_PASSWORD` from `.env`. Vite forwards the API paths to port 8000, so
   the page and the API share one origin and the HttpOnly session cookie just works. Nothing is stored in localStorage
   except the Normal/Brief choice.

For everyday use, `start-mx.ps1` in the project root builds the app (`npm run build` → `web/dist`) when it has
changed and the API serves it at http://localhost:8000.

## Features
- **HUD design** (J.A.R.V.I.S.-inspired, dark only): an animated **mX core** shows standby / thinking / responding / fault, and a floating status card shows a live clock, model, mode, the last reply's tokens and cost, and this session's spend. Wide screens show the card; medium screens move a mini core into the top bar; phones get the chat plus the core.
- **Orbit dial** instead of a sidebar: "+ New" in the center, the 5 most recent chats on spokes, and **All chats** opens a searchable history panel (open, delete, start new). On phones the round button in the top bar opens it.
- Password sign-in; the server sets an HttpOnly session cookie (30 days). **Sign out** is at the bottom of the status card.
- Streaming replies (`fetch` + a stream reader; see `src/sse.ts`), with a **Stop** button. A stopped or failed reply is not saved.
- Normal / Brief mode toggle.
- Images: attach, paste, or drop up to 4 (JPEG, PNG, GIF, WebP, max 5 MB each).
- Markdown, tables, code highlighting, and math (KaTeX) in replies. Raw HTML from the model is never rendered.
- The model, tokens, and cost are shown under each live reply.
- Dark only; the layout works down to phone width.

## Scripts
| Command | What it does |
|---|---|
| `npm run dev` | Dev server on port 5173; API paths are proxied to uvicorn on port 8000 |
| `npm test` | Tests (Vitest): SSE parsing, API client, helpers, components, and App flows against a faked API |
| `npm run coverage` | Tests with a coverage report |
| `npm run typecheck` | TypeScript check |
| `npm run build` | Type-check and build to `dist/` |

## Layout
| File | Role |
|---|---|
| `src/api.ts` | API client (same-origin with the session cookie, typed errors, `login`/`logout`, `streamChat`) |
| `src/sse.ts` | Server-Sent Events parser |
| `src/App.tsx` | State and wiring: conversations, sending, streaming events |
| `src/components/` | `OrbitDial`, `HistoryPanel`, `Core`, `StatusPanel`, `MessageView`, `Composer`, `LoginDialog`, `Markdown`, `StoredImage` |
| `src/markdown.ts` | Keeps `$` prices from being read as math (Pandoc's inline-math rule) |
| `src/styles.css` | Design tokens and the HUD layout |
