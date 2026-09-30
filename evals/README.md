# Evals
`prompts.jsonl` holds test prompts, one JSON object per line:
- required: `id`, `category`, `prompt`, `expect` (what a good answer looks like)
- optional: `mode` (`normal` / `brief`), `history` (earlier `{role, content}` turns), `images` (paths under `evals/images/`)

50 prompts across 16 categories (math, coding, vision, memory, brevity, honesty, and more).

## Running
From the project root, with the venv active. **Real runs call the API and cost money** (about $0.50–$1 for the full set).
```bash
python -m evals.run --dry-run                 # list what would run; free
python -m evals.run                           # all cases with the current prompt
python -m evals.run --prompt-file prompts/mx_system_v2.md --ids p4,p11
python -m evals.run --report evals/results/<run>.jsonl
```
Each case takes the same path as `POST /chat`: the system prompt for its mode, the mode's `max_tokens`/`effort`, and the configured model. `--max-cost` (default $3) stops starting new cases once spend reaches it.

Results go to `evals/results/<timestamp>_<prompt_version>.jsonl` (git-ignored), one row per case: the answer, model, tokens, cost, latency, and `stop_reason`.

## Grading
- `brief` cases are auto-checked: at most 2 sentences, no markdown.
- Everything else is graded pass/fail against `expect` in `<run>.grades.json`, e.g. `{"p4": {"pass": true, "reason": "$0.05 with check"}}`. `--report` merges the grades into the table.
