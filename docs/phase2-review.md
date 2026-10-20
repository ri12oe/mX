# Phase 2 review

Date: 2026-10-20. Scope is `docs/design.md` v0.5. This is a status of what the code contains, not a scored eval run.

## Delivered

- Migrations through `0004_memories.sql`, with a backup before an existing database is upgraded.
- Prompt caching, stepped history, usage rows for failed turns, the budget guard, and `/usage/budget` plus `/usage/summary`.
- Code execution and web search, tool chips, and a Sources list. Citations are labeled "Cited". When an answer has none, the search steps' sources are labeled "Searched". Only `http` and `https` links are clickable.
- `prompts/mx_system_v4.md` is written; after the eval runs, **`prompts/mx_system_v5.md` is the default** (2026-10-20).
- Eval cases p51–p67 cover tools and memory. The runner records tool steps, citations, full cost (including the search fee), and memory proposals.
- Memories: suggest, then Save. `propose_memory` writes nothing. The learner profile is system part 2 when at least one memory exists.
- `docs/phone.md` and `start-mx.ps1 -Phone`. uvicorn stays on `127.0.0.1`. The script never turns on Funnel.
- `Permissions-Policy: microphone=(self), camera=(), geolocation=()`.
- Stretch voice: a mic button when the browser has speech recognition, brief mode for that turn, spoken replies, a stop control, code fences skipped.

## Evals run (2026-10-20, with Rio's OK, $3.43 total)

- **v3 vs v4, all 67 cases:** v4 uses tools far better (code 4/4 vs 2/4, search 3/3 vs 1/3) but sent an
  **empty reply with tools off** (p59). Fixed in code: a tools-off note in the newest message
  (`prompts/tools_off_note_v1.md`) and an `empty_reply` guard in `/chat`.
- **Memory cases (p63–p67)** pass for v4 and v5 (task 26's run).
- **v5** (v4 plus a tighter brief rule) re-run on the 22 affected cases: **20/20 auto-graded pass**, and the
  hand-graded ones are good. **v5 is now the default prompt.** Details: `evals/tuning-log.md`.
- There is still no month of cost-page data, so there is no cache hit rate or month spend to report from the app.

## Still open from the design

- Cache TTL stays `5m` until a week of cost-page data says whether `1h` is worth the higher write price.
- Eval runs do not count toward the in-app $20 budget. The runner's `--max-cost` is the cap. Confirm that is what you want.
- Dismissed suggestions are forgotten on reload, on purpose, so nothing is stored without a yes.
- Tools off uses `tool_choice: none`. The `propose_memory` definition stays in the request so the cache holds, and the model is not allowed to call it.
- Voice depends on the browser. In Chrome, recognition audio goes to Google's speech service even though mX itself is local.

## Out of scope, still

Glasses, wake word, public deploy, web fetch, sandbox file upload or download, embeddings, server-side speech, and a backup model provider.
