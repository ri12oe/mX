# mX — Phase 3 plan (draft)

Owner: Rio · Status: **Draft, awaiting Rio's review** · Written: 2026-10-20

> This is a **plan**, not the design. `docs/design.md` v0.5 stays the source of truth until Rio approves this
> plan; then the architect folds it into `design.md` v0.6 and a week-by-week `TASKS.md`, as for Phase 2.
> Nothing here gets built before that.

## 1. Rio's decisions (2026-10-20)

| Decision | Choice |
|---|---|
| Features | **All four:** AR glasses client · better voice + wake word · context awareness · files and richer tools |
| Glasses | None yet: **recommend one** (§3) |
| Size | **6–8 weeks**, **$20/month** API budget (same guard as Phase 2) |
| Rules that stay | Local only (Tailscale for remote devices, never public), one task per PR, ask before paid API calls, provider SDK only in `providers/`, prompts in `prompts/` |

## 2. Where Phase 2 left off

Phase 2 is implemented (`docs/phase2-review.md`; 429 Python and 146 web tests pass on `main`). It left
loose ends that Phase 3 must close **first**, because the new features stand on them:

1. **Prompt v4 is written but not the default.** mX still runs v3, which says it can't browse or run code,
   so the Phase 2 tools are mostly unused in real chats. The v3 vs v4 eval run (Phase 2 task 20) needs
   Rio's OK (≈ $3–6 for 67 cases).
2. **The memory eval run** (Phase 2 task 26) hasn't happened (≈ $1–2).
3. **No real cost data yet.** The cache TTL (`5m` vs `1h`) and the "is $20 enough?" question need a week
   or two of normal use on the cost page.
4. **Tools-off empty reply** (seen in the task 14 live test): v4 tells mX to answer anyway; the
   `tools_off` evals must confirm it.
5. The command-center layout (PR #44) replaced the orbit dial. New Phase 3 UI follows that layout.

## 3. Glasses recommendation

What mX needs from glasses: a **microphone** (ask by voice), a **display or speaker** (short answers),
ideally a **camera** ("what am I looking at?"), and a way for **mX's own code** to drive them, with no
locked-down app store in the way.

| Glasses | Price (Oct 2026) | Display | Camera | Mic | Speaker | How custom apps work | For mX |
|---|---|---|---|---|---|---|---|
| **Brilliant Labs Halo** | ~$299–349 | color | ✅ 640×480 | ✅ stereo | ✅ bone conduction | **Open source**; a host app drives them over Bluetooth: Python (laptop), Flutter (phone), or **Web Bluetooth in Chrome** (desktop and Android) | **Recommended** |
| Meta Ray-Ban Display | $799 (US only) | ✅ | ✅ 12 MP | ✅ 5 mics | ✅ | Native iOS/Android SDK or web apps; **developer preview, publishing invite-gated**; Meta AI stays closed | Best hardware, least open, most expensive |
| Even Realities G2 | ~$600+ (est.) | text HUD | ❌ | ? | ❌ | TypeScript web apps through the Even iPhone app | No camera, no speaker |

**Recommendation: Brilliant Labs Halo**, because:
- It's the **cheapest** with every sensor mX wants, and it's **open source** (firmware, SDKs), so nothing can
  be revoked by an app-store policy.
- **It fits mX's architecture.** Halo has no app store; a *host* drives it. That host can be the **mX web app
  itself** (Web Bluetooth in Chrome) or a small **Python bridge on the laptop** next to the mX server. Either
  way the glasses talk to the same `/chat` API as every other client (design principle 1).
- The Python SDK has an **emulator**, so most of the glasses work can be built and tested before the
  hardware arrives.

**The deciding question: which phone do you have?**
- **Android:** the mX web app in Chrome (over Tailscale) can drive Halo directly with Web Bluetooth. No new
  app to build. Best case.
- **iPhone:** Safari has no Web Bluetooth. Options: drive Halo from the **laptop** with the Python bridge (works
  at your desk), or a Flutter phone app, which needs a **Mac to build for iPhone**. That's a real constraint on
  Windows. Plan for the laptop bridge first; decide on a phone app after.

Buying glasses is Rio's decision; this plan doesn't assume a purchase until W5. If the hardware is late, W5–W6
run against the Halo emulator and the glasses tasks slide one week (§6).

## 4. Phase 3 scope

### In scope
1. **Close Phase 2** (W1): paid evals with Rio's OK, adopt v4, decide TTL with real data.
2. **Files and richer tools:**
   - **Web fetch** (`web_fetch_20260209`): mX can read a whole page or PDF link you give it. No per-use fee;
     content counts as input tokens, capped by `max_content_tokens`.
   - **PDF and document input:** attach a PDF (homework, slides, a paper) the way images work today.
   - **Sandbox files:** upload a CSV/PDF into code execution and get **plots and files back** (Files API),
     with the code container reused within a chat (Phase 2 kept it to one turn).
3. **Context awareness:**
   - **Time and place in conversation:** today's date, local time, and the day of the week.
   - **Your schedule:** a **read-only calendar feed** (a private ICS link, e.g. from Google Calendar or the
     school's LMS), so mX knows "Calc II exam Thursday" without being told.
   - **A "Now" note:** what you're working on this week (courses, project), editable on a page like Memories.
   - mX uses context only when relevant. Everything stays on the laptop, and calendar text is treated as data,
     never instructions.
4. **Voice v2:**
   - **Push-to-talk everywhere** (laptop, phone, glasses) with one shared flow.
   - **Better, private speech-to-text:** evaluate **local Whisper on the laptop** (free, audio never leaves
     the laptop) against the browser's speech service (free, but Chrome sends audio to Google). Paid cloud
     speech only if both fail; it would need its own budget line.
   - **Spoken answers** from a local text-to-speech voice, so the glasses' speaker can play them.
   - **Wake word "Hey mX"** (stretch): local only, opt-in, off by default.
5. **Glasses client (Halo):**
   - **Ask:** press the glasses' button, speak; the speech goes to mX in brief mode.
   - **See:** the answer on the display (1–2 sentences) and/or spoken through the speaker.
   - **Look:** a "what am I looking at?" press takes **one** photo and sends it with the question
     (image input already exists).
   - Runs through Tailscale like the phone. The glasses are just another client.

### Out of scope (Phase 4 or later)
Continuous recording or an always-on camera (privacy), public deployment, multi-user accounts, Meta/Even
glasses SDKs, embeddings and memory search, fine-tuning, a backup model provider, an iPhone app
(unless Rio has a Mac), and email or messaging integrations.

## 5. Key design questions the architect must settle

| Area | Question | Leaning |
|---|---|---|
| Caching | Context (time, calendar) changes every turn; putting it in the system prompt would break the cache | Put context in the **new user message** (after the cached prefix), not in system parts |
| Context | How much calendar to send? | Next 7 days, titles and times only, ≤ 1,500 characters, stripped of links and descriptions |
| Context | Calendar feed secret | `CALENDAR_ICS_URL` in `.env`; fetched by the server with a timeout and a size cap, cached 15 minutes, never logged |
| Files | Where do uploads live? | Same SQLite DB (like images) up to a size cap; uploaded to Anthropic's Files API only when used, deleted from Anthropic after the chat goes idle |
| Files | Container reuse across turns | Keep the container id per conversation; containers expire (30 days), so handle "expired" by starting fresh |
| Speech | Local Whisper on Windows ARM64 with Smart App Control on | **Spike first:** Smart App Control already blocked one unsigned DLL (pydantic_core). Whisper runtimes ship native DLLs. If blocked, fall back to browser speech |
| Glasses | Bridge: web app vs Python | Android → Web Bluetooth in the web app; iPhone → laptop Python bridge |
| Glasses | Camera privacy | One photo per button press, never video; the photo is stored only if the turn is saved; a visible "captured" indicator on the display |
| Budget | Images, fetched pages and PDFs add input tokens | Keep the $20 guard; add a **per-turn input cap** for fetch/PDF (e.g. 30k tokens) and show it on the cost page |
| Safety | Fetched pages, PDFs and calendar entries can contain prompt injection | Same rule as search results: data, never instructions; add `injection` evals for each new source |

## 6. Timeline (6–8 weeks)

| Week | Focus | Ships | Notes |
|---|---|---|---|
| **W1** | **Close Phase 2** | v3 vs v4 and memory evals (with OK), **v4 adopted**, TTL decision, any fixes the evals show | Makes the tools actually used; everything after builds on v4 |
| **W2** | **Files I: web fetch + PDFs** | `web_fetch` tool, PDF/document attachments, per-turn input cap, fetch evals | Low risk; uses the existing tool plumbing |
| **W3** | **Files II: sandbox files** | Upload CSV/PDF into code execution, plots/files back (download + show in chat), container reuse per chat | Files API (stable, out of beta) |
| **W4** | **Context awareness** | Date/time context, calendar ICS feed, "Now" note page, context evals (relevance + injection) | Context goes after the cached prefix |
| **W5** | **Voice v2** | Speech spike result → local or browser STT, local TTS voice, one push-to-talk flow for laptop and phone | **Spike on day 1:** does local Whisper run under Smart App Control? |
| **W6** | **Glasses I** | Halo bridge (web or Python), button → speak → brief answer on display/speaker | Emulator first if the hardware isn't here |
| **W7** | **Glasses II** | "What am I looking at?" photo, display formatting, battery-friendly behavior, glasses evals | |
| **W8** | **Buffer + Phase 3 review** | Wake word (stretch), slipped tasks, `docs/phase3-review.md` | Hardware delays use this week |

**Slip order** if weeks run long: wake word (to Phase 4) → local TTS (keep browser voice) → sandbox file
download (keep upload) → glasses camera (keep voice + display).

## 7. Budget

- **API: $20/month**, same guard (warning at 80%, brief mode at 100%). New costs to watch:
  - a fetched page or PDF ≈ 2.5k tokens per 10 kB (≈ $0.01) up to the per-turn cap;
  - a glasses photo ≈ 1–1.5k tokens (≈ $0.005);
  - local speech (STT/TTS) costs $0; paid speech would need a separate decision.
- **Evals:** W1 ≈ $4–8 total (paid runs need Rio's OK each time); later weeks ≈ $1–3 each.
- **Hardware (one-time, Rio's purchase):** Halo ~$299–349. Nothing else required; Tailscale is free.
- **Reality check from Phase 2:** a search-backed answer costs ≈ $0.10. If W1–W2 data shows the month
  trending past $20, the plan keeps the guard as is and Rio decides whether to raise the limit.

## 8. Risks

1. **Smart App Control vs native speech libraries.** Local Whisper/TTS may be blocked like pydantic_core
   was. Mitigation: day-1 spike in W5; browser speech is the fallback.
2. **iPhone + Web Bluetooth.** No Web Bluetooth in Safari. Mitigation: laptop Python bridge.
3. **Hardware availability and quality.** A small company; delivery dates have slipped before.
   Mitigation: emulator-first development, and the W8 buffer.
4. **Prompt injection from new sources** (fetched pages, PDFs, calendar). Mitigation: data-not-instructions
   rule, plain-text rendering, and `injection` evals per source.
5. **Cost creep** (pages, PDFs, photos). Mitigation: per-turn input cap, the cost page, the budget guard.
6. **Privacy with a camera on your face.** Mitigation: photo only on a button press, never continuous,
   a visible indicator, nothing stored unless the turn is saved, and nothing ever leaves the laptop except
   to Anthropic for that turn.

## 9. Decisions Rio needs to make (before the architect starts)

1. **Which phone do you have** (Android or iPhone)? This decides the glasses bridge (§3).
2. **Buy the Halo?** Or wait until W5, or pick different glasses.
3. **OK to run the W1 paid evals** (≈ $4–8) and adopt v4 if it wins?
4. **Calendar:** which calendar would mX read (Google, Outlook, school LMS)? It must offer a private
   ICS link.
5. **Speech privacy:** is Chrome sending voice audio to Google acceptable as the fallback, or should voice
   stay laptop-only if local speech doesn't work?

## Sources (glasses research, 2026-10-20)

- Brilliant Labs Halo SDK: <https://docs.brilliant.xyz/halo/halo-sdk/>, Python SDK
  <https://docs.brilliant.xyz/halo/halo-sdk-python/>, hardware <https://docs.brilliant.xyz/halo/hardware/>
- Halo price and launch: <https://roadtovr.com/brilliant-labs-halo-smart-glasses-price-release-date/>,
  <https://yespress.io/brilliant-labs>
- Meta Ray-Ban Display developer access: <https://wearables.developer.meta.com/docs/develop/dat/display-overview/>,
  <https://vr.org/articles/meta-ray-ban-display-developer-sdk-2026>, <https://extentos.com/docs/ecosystem/platforms/meta>
- Meta Ray-Ban Display price: <https://www.telekom.com/en/newsroom/latest-updates/media-information/2026/10/launch-telekom-offers-meta-ray-ban-display>
- Even Realities G2 / Even Hub: <https://hub.evenrealities.com/docs/get-started/overview>,
  <https://www.androidauthority.com/even-realities-g2-smart-glasses-apps-3654769>
