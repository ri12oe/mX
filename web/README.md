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

In production the API serves the built app itself (`npm run build` → `web/dist`, done by the Dockerfile); see
`docs/deploy.md`.

## Features
- Password sign-in; the server sets an HttpOnly session cookie (30 days). **Sign out** is in the sidebar.
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
| `src/components/` | `Sidebar`, `MessageView`, `Composer`, `LoginDialog`, `Markdown`, `StoredImage` |
| `src/markdown.ts` | Keeps `$` prices from being read as math (Pandoc's inline-math rule) |
| `src/styles.css` | Design tokens and layout (light/dark) |
