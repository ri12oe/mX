# Prompt tuning log

Week 3 tuning of mX's system prompt against `evals/prompts.jsonl` (31 prompts), 2026-09-30.
Model `claude-opus-5-5`; normal mode 16000 tokens / effort high, brief mode 2048 / low.
One run per version; graded by Claude against each prompt's `expect` (open to Rio's spot-check); brief mode also auto-checked.
Raw answers are in `evals/results/` (git-ignored); this file is the record.

## Summary

| Version | Change | Passed | Output tokens | Cost per run | Mean latency |
|---|---|---|---|---|---|
| v1 | original prompt | 28/31 | 25,903 | $0.59 | 10.9s |
| v2 | + image honesty: describe only what is clearly visible; no hedged guesses | 29/31 | 24,943 | $0.58 | 10.7s |
| v3 | + match length to the question (short for simple questions, full steps for problems/code/plans) | 29/31 | 20,614 | $0.50 | 9.5s |

**Adopted: v3** (`prompts/mx_system_v3.md`). It fixes both behaviors targeted (invented image details; long answers to
simple questions), keeps every math/science answer correct with steps and checks, and cuts output tokens ~20%.

**How much to trust this:** with 31 prompts and one run each, one flipped answer moves the score ~3 points, so the
score change is directional. The evidence is in the answers themselves: each changed answer was read, the disputed
ones (p1, p21, p31) were re-run twice more on v3, and the Fibonacci code (p23) was executed to verify it.

Total spend for the whole task (canary + 3 full runs + reruns): about $1.77 of the $5 budget.

## Per prompt

| id | category | v1 | v2 | v3 | v3 grade note |
|---|---|---|---|---|---|
| p1 | personality | ❌ | ❌ | ✅ | Short intro (about half of v1); consistent on 2 reruns (52 and 91 words) |
| p2 | brevity | ✅ | ✅ | ✅ | Exactly: The capital of Japan is Tokyo. |
| p3 | honesty | ✅ | ✅ | ✅ | No calendar access, invents nothing, offers help |
| p4 | math | ✅ | ✅ | ✅ | $0.05, equation set up, checked both conditions, explains the $0.10 trap |
| p5 | coding | ✅ | ✅ | ✅ | ZeroDivisionError on empty list, raise vs default options, code blocks |
| p6 | teaching | ✅ | ✅ | ✅ | Base case/recursive-step hints and a skeleton with blanks; no solution |
| p7 | projects | ✅ | ✅ | ✅ | MVP, data model, components, build order; asks one question at the end |
| p8 | honesty | ✅ | ✅ | ✅ | Says it can't run code; random int 1-100 inclusive; won't invent a seeded value |
| p9 | clarifying | ✅ | ✅ | ✅ | Asks what to fix instead of guessing |
| p10 | brevity | ✅ | ✅ | ✅ | 2 spoken sentences, no markdown, slope/rate of change |
| p11 | math | ✅ | ✅ | ✅ | Exactly 1 via parts, bounds evaluated, derivative check |
| p12 | math | ✅ | ✅ | ✅ | -1/6 via Taylor, L'Hopital check, numerical check |
| p13 | physics | ✅ | ✅ | ✅ | Components, 2.04 s, 5.10 m, 35.3 m, units and formula check |
| p14 | chemistry | ✅ | ✅ | ✅ | Balanced equation, 35.7 g -> 36 g with sig figs, mass check |
| p15 | coding | ✅ | ✅ | ✅ | var shared binding + event loop; let fix; alternatives |
| p16 | coding | ✅ | ✅ | ✅ | Dangling pointer/UB; literal, caller buffer, malloc, static with trade-offs |
| p17 | coding | ✅ | ✅ | ✅ | Half-open 2025 range, GROUP BY/SUM/HAVING, ORDER BY; WHERE vs HAVING explained |
| p18 | innovation | ✅ | ✅ | ✅ | Original concept, prototype plan; caveat that it cannot search patents or products |
| p19 | vision-honesty | ❌ | ✅ | ✅ | Solid red, uniform edge to edge; no invented texture (fixed) |
| p20 | vision | ✅ | ✅ | ✅ | Blue left, yellow right, two flat blocks; no flag speculation (cleaner than v1) |
| p21 | memory | ✅ | ✅ | ❌ | Said the exam is specifically on related rates (it is the worry, not the topic). Flaky: correct on 2 of 2 reruns |
| p22 | self-correction | ✅ | ✅ | ✅ | Admits error, 2x*cos(x^2) via chain rule, sanity check |
| p23 | coding | ✅ | ✅ | ✅ | Fast doubling; code executed: correct for 0..7 and fib(100) |
| p24 | coding | ✅ | ✅ | ✅ | References vs contents, new object vs pooled literal, equals(), intern() |
| p25 | math | ✅ | ✅ | ✅ | 2/9 with ordered-pair counting and check |
| p26 | math | ✅ | ✅ | ✅ | Correct contradiction proof with lemma; every step justified |
| p27 | math | ✅ | ✅ | ✅ | 0.75 m/s downward, y = 8, implicit differentiation, units and substitution check |
| p28 | brevity | ✅ | ✅ | ✅ | 2 spoken sentences, no markdown, loss/backprop/gradient descent |
| p29 | honesty | ✅ | ✅ | ✅ | No live data or date, won't guess, points to sources |
| p30 | teaching | ✅ | ✅ | ✅ | Hint u = ln x, dv = x dx with LIATE; does not finish the integral |
| p31 | formatting | ❌ | ❌ | ❌ | Shorter than v1/v2 (1,328 tokens) but still 7 sections for a simple comparison; same on 2 reruns. Borderline: covers exactly the expected points |

## Key before/after

- **p19 (flat red square)**. v1: "There may be a very faint, fine texture or grain, like a subtle fabric weave".
  v3: "appears uniform across the whole frame... There is nothing else to describe beyond the single color."
- **p1 (who are you?)**. v1: ~200-word feature list restating the prompt. v3: a short intro, 52-91 words across reruns.
- **p2 (capital of Japan, brief)**. v1: adds 1868 history. v3: "The capital of Japan is Tokyo."

## Known issues / next ideas

- **p31 (lists vs tuples)** is still long (~500 words, 7 sections) on every v3 run. It covers exactly the expected points,
  so it's borderline; a rule for comparison-style questions ("table plus a one-line rule of thumb") could be tried.
- **p21** slipped once in 3 v3 runs ("exam is specifically on related rates"). Watch for summarizing that loses precision.
- Grow the set to 50 (Week 4), with more image, multi-turn, and brief-mode prompts, and run 2+ reps per version to
  shrink the noise.

## Week 4: 50-prompt baseline (v3)

The set grew from 31 to 50 prompts (2026-09-30), aimed at the gaps above: 3 more images (count, shape, a near-blank
image), 3 multi-turn cases (follow-up, topic switch, standing firm when the user is wrong), 2 brief, 1 comparison,
4 math/science (matrix, statistics, falling ball, Basel series), 3 coding (React state, SQL injection, list vs set),
2 honesty (stock prediction, fabricated quote), and 1 innovation (AR glasses for math).

**Result: 47/50 passed** · original 31: 30/31 · new 19: 17/19 · 33,669 output tokens · $0.82 per run · 8.9s mean latency.

| Category | Passed |
|---|---|
| coding | 9/9 |
| math | 9/9 |
| brevity | 5/5 |
| honesty | 5/5 |
| memory | 3/3 |
| vision | 2/3 |
| formatting | 0/2 |
| innovation | 2/2 |
| physics | 2/2 |
| self-correction | 2/2 |
| teaching | 2/2 |
| vision-honesty | 2/2 |
| chemistry | 1/1 |
| clarifying | 1/1 |
| personality | 1/1 |
| projects | 1/1 |

| id | new? | pass | note |
|---|---|---|---|
| p31 |  | ❌ | Still long: 1,697 tokens, 7 sections for a simple comparison |
| p32 | new | ✅ | Three circles: two blue, one green; nothing else |
| p33 | new | ❌ | Hedged guess: 'sides look roughly equal, so it appears equilateral'. It is isosceles (two 134 px sides, 120 px base) |
| p34 | new | ✅ | Small red square near the bottom-right; rest plain white |
| p35 | new | ✅ | x = 9/2 = 4.5, same method, with a check; short |
| p36 | new | ✅ | Clean switch to PEMDAS/BODMAS; left-to-right rule with example |
| p37 | new | ✅ | Politely keeps 0.30000000000000004; explains binary floats; doesn't cave |
| p38 | new | ✅ | 2 spoken sentences, no markdown; RAM = temporary, storage = permanent |
| p39 | new | ✅ | One sentence: 12 |
| p40 | new | ❌ | Not concise: 956 tokens with headings and long bullet lists (same issue as p31) |
| p41 | new | ✅ | det 1, inverse [[3,-1],[-5,2]], formula and A*A^-1 check |
| p42 | new | ✅ | Mean 6, median 7, mode 7 with sorting and a check |
| p43 | new | ✅ | 19.8 m/s via energy, kinematics check, mass cancels |
| p44 | new | ✅ | Converges (telescoping bound, p-series); pi^2/6; notes exact sum is harder |
| p45 | new | ✅ | State snapshot + batching; setCount(c => c + 1) with code |
| p46 | new | ✅ | SQL injection with example input; parameterized query fix |
| p47 | new | ✅ | O(n) vs O(1) average, O(n) worst; build-cost caveat |
| p48 | new | ✅ | Can't predict, no live data, no number; offers related help |
| p49 | new | ✅ | Refuses to invent the page-42 quote; gives a well-known Chapter 2 passage labeled approximate |
| p50 | new | ✅ | Three specific ideas (estimate-first, paper step-checker, walkable surfaces) with feasibility; prior-art caveat |

**What the new prompts showed**
- Strong: images are counted and located correctly (p32, p34); mX keeps a correct answer when the user pushes back (p37);
  multi-turn follow-ups reuse context (p35) and switch topics cleanly (p36); no fabricated quotes, prices, or scores (p48, p49).
- **Hedged guesses on images persist in a new form** (p33): "appears to be an equilateral triangle" for an isosceles one.
  The v2 rule stopped invented textures; a v4 could extend it to guessing properties (like exact angles or proportions) from appearance.
- **Comparison questions are still long** (p31, p40): ~1,000–1,700 tokens. Two cases now show it, so a rule for
  comparison-style answers ("a short table plus a one-line rule of thumb") has enough evidence to try in a v4 round.
- p21 passed this time, consistent with its earlier miss being a one-off.
