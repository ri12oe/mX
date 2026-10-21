"""Eval runner (design.md §12): run evals/prompts.jsonl through mX and record the answers.

From the project root, with the venv active:
  python -m evals.run --dry-run                          # what would run; no cost
  python -m evals.run                                    # all cases, current prompt
  python -m evals.run --prompt-file prompts/mx_system_v2.md --ids p4,p11
  python -m evals.run --report evals/results/<run>.jsonl # table (with grades, if any)

Each case takes the same path as POST /chat: system parts, caching, tools, and
MODE_OPTIONS, plus the configured provider and model. Real runs cost money;
--max-cost counts tokens and tool fees and stops starting new cases once the
spend reaches it.

Grades live next to a run as <run>.grades.json: {"p4": {"pass": true, "reason": "..."}}.
Brief-mode cases are also auto-checked (at most 2 sentences, no markdown).
"""
import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.chat import build_system, tools_for, turn_cost
from api.config import settings
from api.images import sniff_media_type
from api.prompts import MODE_OPTIONS, check_mode, load_system_prompt, with_tools_off_note
from api.tools import propose_memory_tool
from providers import ModelProvider, create_provider
from providers.base import Citation, ImageData, Message, ModelResponse, ToolStep, UsageMeter
from providers.errors import ProviderError

EVALS_DIR = Path(__file__).parent
PROMPTS_FILE = EVALS_DIR / "prompts.jsonl"
RESULTS_DIR = EVALS_DIR / "results"
DEFAULT_MAX_COST = 3.0
DEFAULT_CONCURRENCY = 4

_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")
_MARKDOWN = re.compile(r"(\*\*|__|`|^\s*#|^\s*[-*+]\s|^\s*\d+[.)]\s|\|.*\|)", re.MULTILINE)


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    prompt: str
    expect: str
    mode: str = "normal"
    history: tuple[tuple[str, str], ...] = ()  # (role, content) turns before the prompt
    images: tuple[str, ...] = ()  # image file paths, relative to the project root
    tools: bool = True  # False = the composer toggle is off for this case
    expect_tools: tuple[str, ...] = ()  # each of these tools must appear in the reply
    expect_no_tools: bool = False
    expect_citations: bool | None = None  # True: at least one; False: none; None: don't check
    memories: tuple[str, ...] = ()  # learner-profile notes for this case only
    expect_memory_proposal: bool | None = None


@dataclass
class Budget:
    limit: float
    spent: float = 0.0
    skipped: list[str] = field(default_factory=list)


# --- Loading -------------------------------------------------------------------


def load_cases(path: Path = PROMPTS_FILE, ids: set[str] | None = None) -> list[EvalCase]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} line {line_number}: invalid JSON ({exc.msg})") from None
        case = EvalCase(
            id=raw["id"], category=raw["category"], prompt=raw["prompt"], expect=raw["expect"],
            mode=raw.get("mode", "normal"),
            history=tuple((turn["role"], turn["content"]) for turn in raw.get("history", [])),
            images=tuple(raw.get("images", [])),
            tools=raw.get("tools", True),
            expect_tools=tuple(raw.get("expect_tools", [])),
            expect_no_tools=bool(raw.get("expect_no_tools", False)),
            expect_citations=raw.get("expect_citations"),
            memories=tuple(raw.get("memories", [])),
            expect_memory_proposal=raw.get("expect_memory_proposal"),
        )
        check_mode(case.mode)
        if ids is None or case.id in ids:
            cases.append(case)
    if ids and len(cases) != len(ids):
        missing = ids - {c.id for c in cases}
        raise ValueError(f"Unknown case id(s): {', '.join(sorted(missing))}")
    return cases


def build_messages(case: EvalCase, root: Path = Path(".")) -> list[Message]:
    """History turns, then the prompt (with its images) as the last user message.

    With tools off, the prompt carries the same tools-off note /chat adds.
    """
    messages = [Message(role=role, content=content) for role, content in case.history]
    images = [load_image(root / p) for p in case.images]
    text = case.prompt if case.tools else with_tools_off_note(case.prompt)
    messages.append(Message(role="user", content=text, images=images or None))
    return messages


def load_image(path: Path) -> ImageData:
    data = path.read_bytes()
    media_type = sniff_media_type(data)
    if media_type is None:
        raise ValueError(f"{path} is not a JPEG, PNG, GIF, or WebP image")
    return ImageData(media_type=media_type, data=data)


# --- Checks --------------------------------------------------------------------


def count_sentences(text: str) -> int:
    return len(_SENTENCE_END.findall(text.strip() + " ")) or (1 if text.strip() else 0)


def auto_checks(
    output: str, case: EvalCase, steps: list[ToolStep], citations: list[Citation],
) -> dict[str, Any] | None:
    """Brief-mode shape, plus tool and citation checks when a case asks for them (design.md §12)."""
    checks: dict[str, Any] = {}
    flags: list[bool] = []
    if not output.strip():  # an empty reply fails every case, graded by hand or not (p59, 2026-10-20)
        checks["answered"] = False
        flags.append(False)
    if case.mode == "brief":
        sentences = count_sentences(output)
        has_markdown = bool(_MARKDOWN.search(output))
        checks["sentences"] = sentences
        checks["markdown"] = has_markdown
        flags.append(sentences <= 2 and not has_markdown)
    if case.expect_tools:
        used = {step.tool for step in steps}
        checks["expect_tools"] = list(case.expect_tools)
        checks["tools"] = all(name in used for name in case.expect_tools)
        flags.append(checks["tools"])
    if case.expect_no_tools:
        checks["no_tools"] = not steps
        flags.append(checks["no_tools"])
    if case.expect_citations is not None:
        # With dynamic filtering, answers often carry no citation blocks (task 16 live test); then the
        # sources a finished search returned are the record, as in the UI's "Searched" list.
        searched = any(step.tool == "web_search" and step.status == "ok" and (step.output or {}).get("sources")
                       for step in steps)
        has_sources = bool(citations) or searched
        checks["citations"] = has_sources is case.expect_citations
        flags.append(checks["citations"])
    if case.expect_memory_proposal is not None:
        proposed = any(step.tool == "propose_memory" and step.status == "ok" for step in steps)
        checks["memory_proposal"] = proposed is case.expect_memory_proposal
        flags.append(checks["memory_proposal"])
    if not checks:
        return None
    return {**checks, "pass": all(flags)}


# --- Running -------------------------------------------------------------------


def step_record(step: ToolStep) -> dict[str, Any]:
    return {
        "id": step.id, "tool": step.tool, "status": step.status,
        "input": step.input, "output": step.output, "error_code": step.error_code,
    }


def reply_cost(reply: ModelResponse) -> float | None:
    """Same total as /chat: cache rates plus tool fees (design.md §9.1)."""
    return turn_cost(UsageMeter(
        input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
        cache_read_tokens=reply.cache_read_tokens,
        cache_write_5m_tokens=reply.cache_write_5m_tokens,
        cache_write_1h_tokens=reply.cache_write_1h_tokens,
        web_searches=reply.web_searches, code_runs=reply.code_runs, model=reply.model,
    ))


async def run_case(provider: ModelProvider, case: EvalCase, prompt_file: str) -> dict[str, Any]:
    prompt = load_system_prompt(case.mode, prompt_file)
    row: dict[str, Any] = {
        "prompt_id": case.id, "category": case.category, "mode": case.mode, "tools": case.tools,
        "prompt": case.prompt, "expect": case.expect, "history": [list(t) for t in case.history],
        "images": list(case.images), "prompt_version": prompt.version,
    }
    started = time.monotonic()
    try:
        reply = await provider.generate(
            build_messages(case), build_system(prompt, list(case.memories)),
            cache_messages=True, cache_ttl=settings.cache_ttl,
            tools=tools_for(case.tools, (propose_memory_tool(),)),
            **MODE_OPTIONS[case.mode],
        )
    except ProviderError as exc:
        return {**row, "error": f"{exc.code}: {exc}", "latency_s": round(time.monotonic() - started, 1)}
    return {
        **row,
        "output": reply.text,
        "model": reply.model,
        "usage": {
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "cache_read_tokens": reply.cache_read_tokens,
            "cache_write_tokens": reply.cache_write_5m_tokens + reply.cache_write_1h_tokens,
            "web_searches": reply.web_searches,
            "code_runs": reply.code_runs,
        },
        "tool_steps": [step_record(step) for step in reply.tool_steps],
        "citations": [{"url": c.url, "title": c.title} for c in reply.citations],
        "cost_usd": reply_cost(reply),
        "latency_s": round(time.monotonic() - started, 1),
        "stop_reason": reply.stop_reason,
        "auto": auto_checks(reply.text, case, reply.tool_steps, reply.citations),
    }


async def run_all(
    provider: ModelProvider, cases: list[EvalCase], prompt_file: str, out: Path,
    budget: Budget, concurrency: int = DEFAULT_CONCURRENCY,
) -> list[dict[str, Any]]:
    """Run cases concurrently, appending each row to `out` as it finishes."""
    semaphore = asyncio.Semaphore(concurrency)
    rows: list[dict[str, Any]] = []
    out.parent.mkdir(parents=True, exist_ok=True)

    async def one(case: EvalCase) -> None:
        async with semaphore:
            if budget.spent >= budget.limit:
                budget.skipped.append(case.id)
                return
            row = await run_case(provider, case, prompt_file)
            budget.spent += row.get("cost_usd") or 0.0
            rows.append(row)
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            status = "ERROR" if "error" in row else f"${row.get('cost_usd') or 0:.4f}"
            print(f"  {len(rows)}/{len(cases)} {case.id:<5} {status}  (spent ${budget.spent:.2f})", flush=True)

    await asyncio.gather(*(one(c) for c in cases))
    return rows


# --- Reporting -----------------------------------------------------------------


def load_grades(results_path: Path) -> dict[str, dict[str, Any]]:
    grades_path = results_path.with_suffix(".grades.json")
    return json.loads(grades_path.read_text(encoding="utf-8")) if grades_path.exists() else {}


def verdict(row: dict[str, Any], grades: dict[str, dict[str, Any]]) -> bool | None:
    """Manual grade if present; for brief mode, it must also pass the auto-checks."""
    if "error" in row:
        return None
    grade = grades.get(row["prompt_id"], {}).get("pass")
    auto = (row.get("auto") or {}).get("pass")
    if grade is None:
        return auto
    return grade and (auto is not False)


def auto_reason(auto: dict[str, Any]) -> str:
    parts: list[str] = []
    if auto.get("answered") is False:
        parts.append("empty reply")
    if "sentences" in auto:
        parts.append(f"{auto['sentences']} sentences, markdown={auto['markdown']}")
    if auto.get("tools") is False:
        parts.append(f"missing tools {auto.get('expect_tools')}")
    if auto.get("no_tools") is False:
        parts.append("used a tool")
    if auto.get("citations") is False:
        parts.append("citations")
    if auto.get("memory_proposal") is False:
        parts.append("memory proposal")
    return ", ".join(parts)


def report(results_path: Path) -> str:
    rows = [json.loads(l) for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows.sort(key=lambda r: int(r["prompt_id"].lstrip("p")) if r["prompt_id"].lstrip("p").isdigit() else 0)
    grades = load_grades(results_path)
    lines = [
        f"Run: {results_path.name}",
        "",
        "| id | category | mode | pass | in / out tokens | cost | s | reason |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        v = verdict(r, grades)
        mark = {True: "✅", False: "❌", None: "—"}[v]
        tokens = f"{r['usage']['input_tokens']} / {r['usage']['output_tokens']}" if "usage" in r else "error"
        reason = grades.get(r["prompt_id"], {}).get("reason") or r.get("error") or ""
        if r.get("auto") and not r["auto"]["pass"]:
            reason = f"auto: {auto_reason(r['auto'])}. {reason}"
        cost = f"${r['cost_usd']:.4f}" if r.get("cost_usd") is not None else "—"
        lines.append(f"| {r['prompt_id']} | {r['category']} | {r['mode']} | {mark} | {tokens} | {cost} | {r['latency_s']} | {reason} |")
    judged = [verdict(r, grades) for r in rows if verdict(r, grades) is not None]
    total_cost = sum(r.get("cost_usd") or 0 for r in rows)
    lines += [
        "",
        f"Passed {sum(judged)}/{len(judged)} graded · errors {sum('error' in r for r in rows)} · "
        f"total cost ${total_cost:.2f} · mean latency {sum(r['latency_s'] for r in rows) / max(len(rows), 1):.1f}s",
    ]
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run mX evals.")
    parser.add_argument("--prompt-file", default=settings.system_prompt_file)
    parser.add_argument("--ids", help="comma-separated case ids (default: all)")
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST, help="stop starting cases at this spend (USD)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true", help="show what would run; no API calls")
    parser.add_argument("--report", type=Path, help="print the table for an existing results file")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to a legacy code page
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.report:
        print(report(args.report))
        return 0

    ids = set(args.ids.split(",")) if args.ids else None
    cases = load_cases(ids=ids)
    version = load_system_prompt("normal", args.prompt_file).version
    modes = {m: sum(c.mode == m for c in cases) for m in MODE_OPTIONS}
    print(f"{len(cases)} cases · model {settings.primary_model} · prompt {version} · modes {modes} "
          f"· max cost ${args.max_cost:.2f}")
    if args.dry_run:
        for c in cases:
            extra = f" +{len(c.history)} history" if c.history else ""
            extra += f" +{len(c.images)} image(s)" if c.images else ""
            extra += "" if c.tools else " tools off"
            print(f"  {c.id:<5} {c.category:<12} {c.mode:<7}{extra}")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"{stamp}_{version}.jsonl"
    provider = create_provider(settings.primary_provider, api_key=settings.anthropic_api_key, model=settings.primary_model)
    budget = Budget(limit=args.max_cost)
    rows = asyncio.run(run_all(provider, cases, args.prompt_file, out, budget, args.concurrency))
    print(f"\nWrote {len(rows)} rows to {out}")
    if budget.skipped:
        print(f"Budget reached: skipped {', '.join(sorted(budget.skipped))}")
    print(report(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
