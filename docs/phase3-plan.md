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

**Eval results, 2026-10-20** (all 67 cases, run with Rio's OK; v4 $1.36 + v3 $1.43 = **$2.79**):

| Area | v4 | v3 |
|---|---|---|
| Uses code when it should (p51–53, p61) | **4/4** | 2/4 |
| Searches when it should (p54–56) | **3/3 searched** | 1/3 |
| Holds back when no tool is needed (p57, p58, p62) | 3/3 | 3/3 |
| Memory: proposes / holds back (p63–66) | 4/4 | 4/4 |
| Prompt injection (p60), uses the profile (p67) | pass / pass | pass / pass |
| Brief answers (5 cases) | 4/5 (p10: 3 sentences) | 5/5 |
| **Tools off (p59)** | ❌ **empty reply** | ✅ answered |

- **v4 is clearly better at using its tools**, and no reply from it was cut off.
- **But v4 sends an empty reply when tools are off** (p59; the auto-check passed it only because it checks
  "no tools used", not "answered"). The reply used 135 output tokens, all hidden thinking: v4 teaches mX to
  search for current facts, so with `tool_choice: none` it wants to search, can't, and stops. The prompt's
  "never send an empty reply" line isn't enough. v3 never wanted to search, so it answers from memory.
- All three search cases "fail" the **citations** check under both versions. That's the dynamic-filtering
  behavior from the task 16 live test (answers carry no citation blocks), not an mX fault: the check is
  too strict.

**So W1 is:** (1) when tools are off, tell mX so in that message (a short note from a `prompts/` file in the
new user turn, after the cached prefix), plus a `/chat` guard that never saves or shows an empty reply
(retry once with that note); (2) eval checks: every case must answer non-empty; citations **or** search
sources count; (3) tighten brief mode for p10; (4) re-run the affected cases (≈ $0.30, with Rio's OK);
(5) adopt v4.
5. The command-center layout (PR #44) replaced the orbit dial. New Phase 3 UI follows that layout.

## 3. Glasses recommendation (updated 2026-10-20: Rio has an **iPhone**)

**The goal, in Rio's words:** *the whole purpose is to show the AI model's chat on the glasses.* So the
display matters most: it must show **several lines of readable text** and work with an **iPhone**. A camera
and a speaker are nice to have.

| Glasses | Price (Oct 2026) | Display | Camera | Mic | Speaker | Works with iPhone + mX? | For mX |
|---|---|---|---|---|---|---|---|
| **Even Realities G2** | **$599** (prescription lenses up to +$159; R1 ring $249 optional) | **Both lenses**, green monochrome, 576×288 px per eye, 27.5° field of view, made for text (teleprompter, notes, translation) | ❌ | ✅ 4-mic array (16 kHz) | ❌ | ✅ Apps are **TypeScript web apps** inside the Even iPhone app; they can call **whitelisted servers**, e.g. mX over Tailscale | **Recommended** |
| Brilliant Labs Halo | ~$299–349 | **Tiny 0.2" color display** at the top of the frame (you glance up; ~256×256 drawable) | ✅ | ✅ | ✅ | ⚠️ No Web Bluetooth on iPhone; a phone app needs a **Mac** to build, so laptop bridge only | Glance display: too small to read a chat |
| Meta Ray-Ban Display | $799 (US only) | color, one lens | ✅ | ✅ | ✅ | ⚠️ The iOS SDK needs a **Mac/Xcode**; developer access is preview/invite-gated | Expensive, least open |

**Recommendation: Even Realities G2.**
- It's **built for reading text**: a display in both eyes, sharp at any focus distance (per reviewers), and
  about **3 days** of battery. The chat is the point, and this is the one designed to show it.
- It's **the right fit for an iPhone and a Windows laptop**. G2 apps are **web apps** (HTML/TypeScript, built
  with Vite like mX's own web app) that run inside the Even app on your iPhone. No Mac needed.
- **It can reach mX privately:** a G2 app may call servers listed in its network whitelist, so it can call
  `https://<laptop>.<tailnet>.ts.net` through the iPhone's Tailscale. mX stays local-only.
- **You can run your own app:** testing supports a QR sideload or a private build in the developer portal.
  No public store listing needed.

**Trade-offs:**
- **No camera**, so "what am I looking at?" moves out of the glasses. The **iPhone camera** can do it instead
  (mX already takes images).
- **No speaker:** answers are **read on the display**, which is the goal. Spoken answers stay on the phone or
  laptop.
- **Green monochrome:** fine for text, not for images or colored math. Long answers need paging (brief mode
  fits best).
- Outdoors in bright sun, reviewers say the sunglass clip-on ($99) is needed.

**Verify before buying** (a short W1 spike using the Even Hub **simulator**, which is free with no glasses):
1. A G2 app can call mX over Tailscale (whitelist + CORS) from the iPhone.
2. The SDK gives apps the **microphone** stream (the hardware has it; the API isn't confirmed in the docs I read).
3. How much text fits and how pages scroll (the "Display & UI" docs).

If any of these fails, the fallback is a **phone-first** design: the mX web app on the iPhone stays the main
screen, and the glasses only show the latest answer. Buying the G2 is Rio's decision; the plan doesn't assume
a purchase until the spike passes.

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
   - **Spoken answers** from a better voice on the laptop and phone (the G2 has no speaker; on the
     glasses, answers are read).
   - **Wake word "Hey mX"** (stretch): local only, opt-in, off by default.
5. **Glasses client (Even Realities G2):**
   - **An Even Hub app** (TypeScript, Vite) that runs in the Even app on the iPhone and talks to the mX API
     over Tailscale. The glasses are just another client.
   - **Read the chat:** the latest question and mX's answer on the glasses, paged with swipes (brief mode
     by default, normal on request).
   - **Ask:** long-press the touchpad (or the R1 ring), speak; the glasses' mics → speech-to-text → mX.
   - **Follow along:** messages sent from the phone or laptop also appear on the glasses.
   - **Look:** "what am I looking at?" uses the **iPhone camera** (the G2 has none).

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
| Glasses | How the G2 app signs in to mX | A dedicated **device token** (revocable, chat-only), not the main API key or the password; CORS allows only the Even app's origin |
| Glasses | Showing long answers on a 576×288 green display | Brief mode by default, paging by swipe, markdown flattened to plain text, math as plain text |
| Budget | Images, fetched pages and PDFs add input tokens | Keep the $20 guard; add a **per-turn input cap** for fetch/PDF (e.g. 30k tokens) and show it on the cost page |
| Safety | Fetched pages, PDFs and calendar entries can contain prompt injection | Same rule as search results: data, never instructions; add `injection` evals for each new source |

## 6. Timeline (6–8 weeks)

| Week | Focus | Ships | Notes |
|---|---|---|---|
| **W1** | **Close Phase 2 + G2 spike** | v3 vs v4 and memory evals, **v4 adopted**, TTL decision; **Even Hub simulator spike** (Tailscale call, mic API, text layout) | The evals started 2026-10-20 with Rio's OK; the spike decides whether to buy the G2 |
| **W2** | **Files I: web fetch + PDFs** | `web_fetch` tool, PDF/document attachments, per-turn input cap, fetch evals | Low risk; uses the existing tool plumbing |
| **W3** | **Files II: sandbox files** | Upload CSV/PDF into code execution, plots/files back (download + show in chat), container reuse per chat | Files API (stable, out of beta) |
| **W4** | **Context awareness** | Date/time context, calendar ICS feed, "Now" note page, context evals (relevance + injection) | Context goes after the cached prefix |
| **W5** | **Voice v2** | Speech spike result → local or browser STT, local TTS voice, one push-to-talk flow for laptop and phone | **Spike on day 1:** does local Whisper run under Smart App Control? |
| **W6** | **Glasses I** | Even Hub app: device token, read the latest Q&A on the glasses, paging, follow chats from phone/laptop | Simulator first if the glasses aren't here |
| **W7** | **Glasses II** | Ask by voice from the glasses (long-press → mic → STT → mX), plain-text formatting for the green display, iPhone-camera "look", glasses evals | |
| **W8** | **Buffer + Phase 3 review** | Wake word (stretch), slipped tasks, `docs/phase3-review.md` | Hardware delays use this week |

**Slip order** if weeks run long: wake word (to Phase 4) → local TTS (keep browser voice) → sandbox file
download (keep upload) → iPhone-camera "look" (keep reading + voice on the glasses).

## 7. Budget

- **API: $20/month**, same guard (warning at 80%, brief mode at 100%). New costs to watch:
  - a fetched page or PDF ≈ 2.5k tokens per 10 kB (≈ $0.01) up to the per-turn cap;
  - a glasses photo ≈ 1–1.5k tokens (≈ $0.005);
  - local speech (STT/TTS) costs $0; paid speech would need a separate decision.
- **Evals:** W1 ≈ $4–8 total (paid runs need Rio's OK each time); later weeks ≈ $1–3 each.
- **Hardware (one-time, Rio's purchase):** Even Realities G2 **$599** (+ prescription lenses up to $159;
  the R1 ring $249 and sunglass clip-on $99 are optional). Buy only after the W1 simulator spike passes.
  Tailscale is free.
- **Reality check from Phase 2:** a search-backed answer costs ≈ $0.10. If W1–W2 data shows the month
  trending past $20, the plan keeps the guard as is and Rio decides whether to raise the limit.

## 8. Risks

1. **Smart App Control vs native speech libraries.** Local Whisper/TTS may be blocked like pydantic_core
   was. Mitigation: day-1 spike in W5; browser speech is the fallback.
2. **The G2 app platform is young** (Even Hub launched in March 2026; SDK version 0.0.x). APIs may change,
   and microphone access for apps isn't confirmed. Mitigation: the W1 simulator spike, buying only after
   it passes, and a phone-first fallback.
3. **Hardware availability and quality.** Mitigation: simulator-first development, and the W8 buffer.
4. **Prompt injection from new sources** (fetched pages, PDFs, calendar). Mitigation: data-not-instructions
   rule, plain-text rendering, and `injection` evals per source.
5. **Cost creep** (pages, PDFs, photos). Mitigation: per-turn input cap, the cost page, the budget guard.
6. **A device token on the phone.** The G2 app needs a way to sign in. Mitigation: a chat-only,
   revocable device token (not the main key or password), and Tailscale-only access.

## 9. Decisions Rio needs to make (before the architect starts)

1. ~~Which phone?~~ **iPhone** (Rio, 2026-10-20), so the recommendation is the **Even Realities G2** (§3).
2. **Buy the G2 after the W1 simulator spike passes?** ($599, + prescription lenses if you need them.)
3. ~~OK to run the W1 paid evals?~~ **Yes** (Rio, 2026-10-20); the runs started, $4 cap per prompt version.
4. **Calendar:** which calendar would mX read (Google, Outlook, school LMS)? It must offer a private
   ICS link.
5. **Speech privacy:** is Chrome sending voice audio to Google acceptable as the fallback, or should voice
   stay laptop-only if local speech doesn't work?

## Sources (glasses research, 2026-10-20)

- Even Realities G2 review (price, display, battery): <https://9to5google.com/review-even-realities-g2-smart-glasses/>
- Even Hub overview (specs, app model, testing): <https://hub.evenrealities.com/docs/get-started/overview>,
  architecture <https://hub.evenrealities.com/docs/get-started/architecture>, FAQ (network whitelist, CORS)
  <https://hub.evenrealities.com/docs/reference/faq>, local testing <https://hub.evenrealities.com/docs/test/local-testing>
- G2 display specs (27.5° FoV): <https://www.knoxlabs.com/products/even-realities-g2-ai-glasses>, <https://heise.de/-11076939>
- Halo display (0.2" OLEDoS, glance display): <https://docs.brilliant.xyz/halo/hardware/>,
  <https://www.auganix.org/xr-news-brilliant-labs-halo-ai-glasses/>

- Brilliant Labs Halo SDK: <https://docs.brilliant.xyz/halo/halo-sdk/>, Python SDK
  <https://docs.brilliant.xyz/halo/halo-sdk-python/>, hardware <https://docs.brilliant.xyz/halo/hardware/>
- Halo price and launch: <https://roadtovr.com/brilliant-labs-halo-smart-glasses-price-release-date/>,
  <https://yespress.io/brilliant-labs>
- Meta Ray-Ban Display developer access: <https://wearables.developer.meta.com/docs/develop/dat/display-overview/>,
  <https://vr.org/articles/meta-ray-ban-display-developer-sdk-2026>, <https://extentos.com/docs/ecosystem/platforms/meta>
- Meta Ray-Ban Display price: <https://www.telekom.com/en/newsroom/latest-updates/media-information/2026/10/launch-telekom-offers-meta-ray-ban-display>
- Even Realities G2 / Even Hub: <https://hub.evenrealities.com/docs/get-started/overview>,
  <https://www.androidauthority.com/even-realities-g2-smart-glasses-apps-3654769>
