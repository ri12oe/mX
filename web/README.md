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
3. Open http://localhost:5173 and enter the API address (`http://127.0.0.1:8000`) and your `MX_API_KEY` from `.env`.
   They're saved in this browser only (localStorage).

## Features
- Streaming replies (`fetch` + a stream reader; see `src/sse.ts`), with a **Stop** button. A stopped or failed reply is not saved.
- Normal / Brief mode toggle.
- Images: attach, paste, or drop up to 4 (JPEG, PNG, GIF, WebP, max 5 MB each).
- Markdown, tables, code highlighting, and math (KaTeX) in replies. Raw HTML from the model is never rendered.
- Conversation list: open, start new, delete. The model, tokens, and cost are shown under each live reply.
- Light and dark themes follow your system setting; the layout works down to phone width.

## Scripts
| Command | What it does |
|---|---|
| `npm run dev` | Dev server on port 5173 (the origin the API's CORS allows) |
| `npm test` | Unit tests (Vitest): SSE parsing, API client, helpers |
| `npm run typecheck` | TypeScript check |
| `npm run build` | Type-check and build to `dist/` |

## Layout
| File | Role |
|---|---|
| `src/api.ts` | API client (`X-mX-Key` on every call, typed errors, `streamChat`) |
| `src/sse.ts` | Server-Sent Events parser |
| `src/App.tsx` | State and wiring: conversations, sending, streaming events |
| `src/components/` | `Sidebar`, `MessageView`, `Composer`, `KeyDialog`, `Markdown`, `AuthImage` |
| `src/markdown.ts` | Keeps `$` prices from being read as math (Pandoc's inline-math rule) |
| `src/styles.css` | Design tokens and layout (light/dark) |
