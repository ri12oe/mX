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
