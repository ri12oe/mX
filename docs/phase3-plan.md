# mX — Phase 3 plan (draft)

Owner: Rio · Status: **Draft, awaiting Rio's review** · Written: 2026-10-20 · Updated: 2026-10-20 (DIY glasses)

> This is a **plan**, not the design. `docs/design.md` v0.5 stays the source of truth until Rio approves this
> plan; then the architect folds it into `design.md` v0.6 and a week-by-week `TASKS.md`, as for Phase 2.
> Nothing here gets built before that.

## 1. Rio's decisions (2026-10-20)

| Decision | Choice |
|---|---|
| Features | **All four:** AR glasses client · better voice + wake word · context awareness · files and richer tools |
| Glasses | **DIY custom glasses** (Rio, 2026-10-20), after comparing the G2, Meta and Halo (§3) |
| DIY constraints | Parts **$100–250** · **no tools yet** (no soldering iron or 3D printer) · **at the desk first** · **display first, camera second** |
| Phone | **iPhone**; laptop is Windows (no Mac) |
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

**Done in PR #46 (Phase 2 wrap-up, 2026-10-20):** a tools-off note in the newest message plus an
`empty_reply` guard in `/chat`; eval checks (an empty reply fails; searched sources count); prompt v5
(v4 + a tighter brief rule) re-run on the 22 affected cases (**20/20**, $0.64) and **adopted as the default**.
Total eval spend: $3.43.
5. The command-center layout (PR #44) replaced the orbit dial. New Phase 3 UI follows that layout.

## 3. Glasses: DIY (Rio's decision, 2026-10-20)

**Goal:** see mX's chat on the glasses; later, tap to take a picture and get an answer. **Constraints:**
$100–250 for parts, no tools yet, at the desk first, display before camera, an iPhone, and a Windows laptop.

### The build
| Step | Hardware | Tools needed | ~Cost |
|---|---|---|---|
| **v1: display** | **LILYGO T-Glass**: ESP32-S3, prism display (**126×126 visible pixels**), microphone, touch button, vibration motor, IMU, battery, Wi-Fi + Bluetooth LE | **None**: USB-C to flash and charge | $48–90 |
| **v2: camera** | **Seeed XIAO ESP32S3 Sense** (camera + mic, Wi-Fi/BLE), a small LiPo battery, a clip or mount | **Soldering** (battery wires) and a mount: a makerspace, or a ~$30 starter soldering kit | $25–45 |
| Spare/misc | USB-C cable, a spare battery, clips | – | $15–30 |

Total ≈ **$90–165**, inside the $100–250 budget, with room for a soldering kit.

**What the display can show:** 126×126 pixels is about **8 lines of ~20 characters**. That fits a **brief
answer, paged** with the touch button, plus a one-line status ("Listening…", "Thinking…"). It isn't a full chat
window: **brief mode is the glasses' native mode**, and the full chat stays on the laptop and phone.

### How it connects (no Mac, no extra install)
- **The mX web app is the bridge.** In **Edge or Chrome on the laptop**, the web app connects to the glasses
  with **Web Bluetooth** (a browser feature) and sends them the latest question and answer as they stream.
  The glasses never talk to the server directly, so they need no password or token, and mX stays bound to
  `127.0.0.1`.
- **Why not a Python bridge:** Python Bluetooth libraries on Windows use native components, and Smart App
  Control has already blocked one unsigned native library (pydantic_core). The browser avoids that.
- **Later, "anywhere":** the free iPhone browser **Bluefy** supports Web Bluetooth. Opening mX (over
  Tailscale HTTPS) in Bluefy could run the same bridge code on the iPhone. That's a Phase 3 stretch / Phase 4 test.
- **Firmware** (the program on the glasses): an ESP32 Arduino sketch based on LILYGO's T-Glass examples,
  flashed over USB-C. If Smart App Control blocks the Arduino toolchain, flash from the browser instead
  (Web Serial / ESP Web Tools).

### Why DIY over the G2 / Meta (for the record)
DIY is cheaper, fully under mX's control, works with an iPhone and Windows without a Mac, and can get a camera
(v2), which neither the G2 (no camera) nor the Meta web apps (no camera access) offer here. The trade-offs:
a much **smaller, simpler display**, a **hardware project** (risk, time, comfort), and **desk-only at first**.
The comparison that led here is kept below.

### Background: the commercial glasses compared (2026-10-20)

**The goal, in Rio's words:** *the whole purpose is to show the AI model's chat on the glasses.* So the
display matters most: it must show **several lines of readable text** and work with an **iPhone**. A camera
and a speaker are nice to have.

| Glasses | Price (Oct 2026) | Display | Camera | Mic | Speaker | Works with iPhone + mX? | For mX |
|---|---|---|---|---|---|---|---|
| **Even Realities G2** | **$599** (prescription lenses up to +$159; R1 ring $249 optional) | **Both lenses**, green monochrome, 576×288 px per eye, 27.5° field of view, made for text (teleprompter, notes, translation) | ❌ | ✅ 4-mic array (16 kHz) | ❌ | ✅ Apps are **TypeScript web apps** inside the Even iPhone app; they can call **whitelisted servers**, e.g. mX over Tailscale | **Recommended** |
| Brilliant Labs Halo | ~$299–349 | **Tiny 0.2" color display** at the top of the frame (you glance up; ~256×256 drawable) | ✅ | ✅ | ✅ | ⚠️ No Web Bluetooth on iPhone; a phone app needs a **Mac** to build, so laptop bridge only | Glance display: too small to read a chat |
| Meta Ray-Ban Display | $799 (US only) | color, one lens | ✅ | ✅ | ✅ | ⚠️ The iOS SDK needs a **Mac/Xcode**; developer access is preview/invite-gated | Expensive, least open |

**Earlier recommendation, superseded by DIY (§3): Even Realities G2.**
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

**Could the Meta Ray-Ban Display give us the camera? (researched 2026-10-20)**
- **Web apps** (HTML/JS, added by typing a URL in the Meta AI phone app with Developer Mode on; **no Mac**):
  they run on the glasses and can use motion, phone GPS, the Neural Band, local storage, and text input by
  **dictation**. **The camera and microphone are not listed for web apps.** It's also unclear whether they
  can reach a private Tailscale address; Meta's docs assume a hosted server.
- **The camera needs the native Device Access Toolkit** (Swift on iPhone), which means **Xcode on a Mac**,
  or an Android phone (Kotlin).
- So with an iPhone and a Windows laptop, the Meta glasses give a display plus dictation, **but no camera**:
  the same as the G2, for $200 more, with a one-lens 600×600 display, still a developer preview.
- **Revisit if** Meta adds the camera to web apps, or Rio gets a Mac.

**DIY glasses (researched 2026-10-20):** possible, but a hardware project, not a weekend:
- **Display:** the LILYGO T-Glass (ESP32-S3, 1.1" color prism display, mic, touch button; no camera) is the
  closest kit. The text area is small, and an ESP32 can show simple text but not a rich chat UI.
- **Camera:** OpenGlass (an ESP32-S3 camera on any frame, under $25 in parts) shows the idea, but has **no
  display** and is no longer maintained (moved to Omi).
- **Combining both** means custom wiring, a 3D-printed mount, batteries, firmware, and optics. The hardest
  part, a bright, readable see-through display, is what the $599 G2 already solves. An ESP32 also can't join
  Tailscale, so it would need the laptop as a Bluetooth bridge (desk only), or a phone app (Mac again on iPhone).
- A fun Phase 4 side project, not the path to reading the chat on your glasses this term.

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
5. **DIY glasses (§3):**
   - **v1 display (T-Glass):** firmware that shows text sent over Bluetooth LE, pages it with the touch
     button, and shows a status line; a **Glasses panel** in the mX web app that connects with Web Bluetooth
     (Edge/Chrome on the laptop) and mirrors the latest question and answer as they stream, flattened to plain text.
   - **Ask from the glasses:** a long-press sends "start talking". Speech comes from the laptop mic at first;
     the glasses' own mic only if local speech-to-text works (W5 spike), since the browser's speech service
     can't take audio from a Bluetooth device.
   - **v2 camera (stretch, needs soldering):** the XIAO ESP32S3 Sense takes **one** photo on a tap and sends it
     through the same bridge as an image attachment.
   - **Anywhere (stretch):** the same bridge in Bluefy on the iPhone.

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
| Glasses | Bluetooth protocol | One custom BLE service: a text characteristic (chunked UTF-8, ≤ 180 bytes per write), a status characteristic, and button events as notifications; versioned so firmware and web app can change separately |
| Glasses | Showing answers on 126×126 pixels | Brief mode by default; markdown, code and math flattened to plain text; ~8 lines × ~20 characters per page; the button pages; a long-press asks |
| Glasses | Pairing and privacy | Web Bluetooth needs a user click to pair (a browser rule); only mX's own service UUID is requested; nothing is stored on the glasses except the current page |
| Budget | Images, fetched pages and PDFs add input tokens | Keep the $20 guard; add a **per-turn input cap** for fetch/PDF (e.g. 30k tokens) and show it on the cost page |
| Safety | Fetched pages, PDFs and calendar entries can contain prompt injection | Same rule as search results: data, never instructions; add `injection` evals for each new source |

## 6. Timeline (6–8 weeks)

| Week | Focus | Ships | Notes |
|---|---|---|---|
| **W1** | **Order parts** | Phase 2 is closed (PR #46: evals run, empty-reply fix, **prompt v5 adopted**); order the **T-Glass**; TTL decision once there's data | Shipping can take 1–3 weeks, so order now |
| **W2** | **Files I: web fetch + PDFs** | `web_fetch` tool, PDF/document attachments, per-turn input cap, fetch evals | Low risk; uses the existing tool plumbing |
| **W3** | **Files II: sandbox files** | Upload CSV/PDF into code execution, plots/files back (download + show in chat), container reuse per chat | Files API (stable, out of beta) |
| **W4** | **Context awareness** | Date/time context, calendar ICS feed, "Now" note page, context evals (relevance + injection) | Context goes after the cached prefix |
| **W5** | **Voice v2** | Speech spike result → local or browser STT, local TTS voice, one push-to-talk flow for laptop and phone | **Spike on day 1:** does local Whisper run under Smart App Control? |
| **W6** | **Glasses I: display** | T-Glass firmware (BLE text + paging + status), the web app's Glasses panel (Web Bluetooth in Edge/Chrome), the latest Q&A streaming to the glasses | Flashing toolchain check on day 1 (Smart App Control) |
| **W7** | **Glasses II: asking** | Long-press to ask (laptop mic; the glasses' mic if local STT works), plain-text formatting, brief-mode evals for the glasses | |
| **W8** | **Buffer + Phase 3 review** | Stretch: **camera board (v2)** if soldering is set up; **Bluefy on the iPhone**; wake word. Slipped tasks, `docs/phase3-review.md` | Hardware delays use this week |

**Slip order** if weeks run long: wake word (to Phase 4) → local TTS (keep browser voice) → sandbox file
download (keep upload) → glasses camera v2 and Bluefy (keep the display + asking at the desk).

## 7. Budget

- **API: $20/month**, same guard (warning at 80%, brief mode at 100%). New costs to watch:
  - a fetched page or PDF ≈ 2.5k tokens per 10 kB (≈ $0.01) up to the per-turn cap;
  - a glasses photo ≈ 1–1.5k tokens (≈ $0.005);
  - local speech (STT/TTS) costs $0; paid speech would need a separate decision.
- **Evals:** W1 ≈ $4–8 total (paid runs need Rio's OK each time); later weeks ≈ $1–3 each.
- **Hardware (one-time, Rio's purchase, DIY):** ≈ **$90–165** of the $100–250 budget: T-Glass $48–90 now;
  camera board + battery $25–45 and an optional ~$30 soldering kit for v2. Tailscale and Bluefy are free.
- **Reality check from Phase 2:** a search-backed answer costs ≈ $0.10. If W1–W2 data shows the month
  trending past $20, the plan keeps the guard as is and Rio decides whether to raise the limit.

## 8. Risks

1. **Smart App Control vs native speech libraries.** Local Whisper/TTS may be blocked like pydantic_core
   was. Mitigation: day-1 spike in W5; browser speech is the fallback.
2. **DIY hardware risk:** a small display (126×126), comfort and weight, battery life, and stock (the T-Glass
   has been out of stock at times). Mitigation: order in W1, brief mode as the glasses' native mode, and the
   W8 buffer. Nothing in mX depends on the glasses, so a hardware problem can't break the app.
3. **Flashing toolchain vs Smart App Control** (Arduino/esptool binaries). Mitigation: flash from the
   browser (Web Serial / ESP Web Tools) if blocked.
4. **Prompt injection from new sources** (fetched pages, PDFs, calendar). Mitigation: data-not-instructions
   rule, plain-text rendering, and `injection` evals per source.
5. **Cost creep** (pages, PDFs, photos). Mitigation: per-turn input cap, the cost page, the budget guard.
6. **Bluetooth is short-range and unencrypted by default.** Mitigation: the glasses only receive the text
   already on Rio's screen; they hold no password or token; pairing needs a click in the browser.

## 9. Decisions Rio needs to make (before the architect starts)

1. ~~Which phone?~~ **iPhone** (Rio, 2026-10-20). ~~Which glasses?~~ **DIY** (Rio, 2026-10-20; §3).
2. **Order the LILYGO T-Glass** (~$48–90) in W1? It's the v1 display, and stock varies, so check the LILYGO
   store first.
6. **For the v2 camera:** a makerspace, or a ~$30 starter soldering kit?
3. ~~OK to run the W1 paid evals?~~ **Yes** (Rio, 2026-10-20); the runs started, $4 cap per prompt version.
4. **Calendar:** which calendar would mX read (Google, Outlook, school LMS)? It must offer a private
   ICS link.
5. **Speech privacy:** is Chrome sending voice audio to Google acceptable as the fallback, or should voice
   stay laptop-only if local speech doesn't work?

## Sources (glasses research, 2026-10-20)

- LILYGO T-Glass: wiki <https://wiki.lilygo.cc/get_started/en/Wearable/T-Glass/T-Glass.html>,
  <https://www.cnx-software.com/2024/07/01/lilygo-t-glass-esp32-powered-smart-glasses-with-1-1-inch-prism-display-imu-microphone/>,
  <https://openelab.io/products/lilygo-t-glass-diy-prism-display-glasses>
- Seeed XIAO ESP32S3 Sense: <https://www.atomic14.com/esp32/boards/xiao-esp32-s3/>,
  <https://www.pakronics.com.au/products/seeed-studio-xiao-esp32s3-sense-ss113991115>
- Bluefy (Web Bluetooth on iOS): <https://apps.apple.com/app/id1492822055>

- Even Realities G2 review (price, display, battery): <https://9to5google.com/review-even-realities-g2-smart-glasses/>
- Even Hub overview (specs, app model, testing): <https://hub.evenrealities.com/docs/get-started/overview>,
  architecture <https://hub.evenrealities.com/docs/get-started/architecture>, FAQ (network whitelist, CORS)
  <https://hub.evenrealities.com/docs/reference/faq>, local testing <https://hub.evenrealities.com/docs/test/local-testing>
- G2 display specs (27.5° FoV): <https://www.knoxlabs.com/products/even-realities-g2-ai-glasses>, <https://heise.de/-11076939>
- Meta web apps and toolkit: <https://developers.meta.com/wearables/faq/>,
  <https://ppc.land/meta-opens-display-glasses-to-developers-with-two-sdk-paths/>,
  <https://wearables.developer.meta.com/docs/develop/dat/display-overview/>
- DIY: OpenGlass <https://github.com/BasedHardware/OpenGlass>, LILYGO T-Glass
  <https://www.cnx-software.com/2024/07/01/lilygo-t-glass-esp32-powered-smart-glasses-with-1-1-inch-prism-display-imu-microphone/>;
  MentraOS (open-source glasses OS) <https://heise.de/-10475558>
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
