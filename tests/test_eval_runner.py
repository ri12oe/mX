"""evals/run.py with the FakeProvider (no cost)."""
import asyncio
import json
from pathlib import Path

import pytest

from api.config import settings
from evals import run as runner
from providers.errors import ProviderUnavailableError
from tests.fakes import FakeProvider

PROMPT_FILE = settings.system_prompt_file


# --- The real eval set ---------------------------------------------------------


def test_real_eval_set_loads_with_unique_ids_and_existing_images():
    cases = runner.load_cases()
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)) >= 50
    for case in cases:
        assert case.prompt and case.expect
        for image in case.images:
            assert Path(image).is_file(), image
        for role, _ in case.history:
            assert role in ("user", "assistant")


def test_every_case_builds_valid_messages():
    for case in runner.load_cases():
        messages = runner.build_messages(case)
        assert messages[0].role == "user" and messages[-1].role == "user"
        assert messages[-1].content == case.prompt


def test_load_cases_filters_and_rejects_unknown_ids():
    assert [c.id for c in runner.load_cases(ids={"p2", "p4"})] == ["p2", "p4"]
    with pytest.raises(ValueError, match="p999"):
        runner.load_cases(ids={"p2", "p999"})


def test_build_messages_includes_history_and_images():
    case = runner.EvalCase(
        id="x", category="c", prompt="And now?", expect="e",
        history=(("user", "Hi"), ("assistant", "Hello")),
        images=("evals/images/red_square.png",),
    )
    messages = runner.build_messages(case)
    assert [(m.role, m.content) for m in messages] == [("user", "Hi"), ("assistant", "Hello"), ("user", "And now?")]
    assert messages[-1].images is not None and messages[-1].images[0].media_type == "image/png"


# --- Brief-mode auto-checks --------------------------------------------------


@pytest.mark.parametrize(
    ("text", "sentences"),
    [("Tokyo.", 1), ("It is Tokyo. Japan's capital!", 2), ("One. Two. Three.", 3), ("No period", 1), ("", 0),
     ("It's about 3.14 in value.", 1)],
)
def test_count_sentences(text: str, sentences: int):
    assert runner.count_sentences(text) == sentences


@pytest.mark.parametrize(
    ("text", "passes"),
    [
        ("The capital of Japan is Tokyo.", True),
        ("It's Tokyo. It's also the largest city.", True),
        ("One. Two. Three.", False),
        ("**Tokyo** is the capital.", False),
        ("- Tokyo", False),
        ("Use `print()` to show it.", False),
    ],
)
def test_brief_auto_checks(text: str, passes: bool):
    assert runner.auto_checks(text, "brief")["pass"] is passes  # type: ignore[index]


def test_normal_mode_has_no_auto_checks():
    assert runner.auto_checks("**anything**", "normal") is None


# --- Running -----------------------------------------------------------------


def run(cases: list[runner.EvalCase], fake: FakeProvider, out: Path, limit: float = 10.0) -> runner.Budget:
    budget = runner.Budget(limit=limit)
    asyncio.run(runner.run_all(fake, cases, PROMPT_FILE, out, budget, concurrency=1))
    return budget


def test_run_all_writes_one_row_per_case_with_usage_and_cost(tmp_path: Path):
    fake = FakeProvider(chunks=["It is Tokyo."], model="claude-opus-5-5", input_tokens=1000, output_tokens=100)
    out = tmp_path / "run.jsonl"
    run(runner.load_cases(ids={"p2", "p4"}), fake, out)

    rows = {r["prompt_id"]: r for r in map(json.loads, out.read_text(encoding="utf-8").splitlines())}
    assert set(rows) == {"p2", "p4"}
    p2 = rows["p2"]
    assert (p2["output"], p2["model"], p2["prompt_version"]) == ("It is Tokyo.", "claude-opus-5-5", "mx_system_v3")
    assert p2["usage"] == {"input_tokens": 1000, "output_tokens": 100}
    assert p2["cost_usd"] == pytest.approx(0.006)
    assert p2["auto"]["pass"] is True and rows["p4"]["auto"] is None


def test_run_uses_the_same_prompt_and_mode_options_as_chat(tmp_path: Path):
    fake = FakeProvider()
    run(runner.load_cases(ids={"p2"}), fake, tmp_path / "run.jsonl")
    call = fake.calls[0]
    assert call.method == "generate"
    assert "Mode: brief" in call.system and call.opts == {"max_tokens": 2048, "effort": "low"}


def test_provider_errors_become_error_rows(tmp_path: Path):
    fake = FakeProvider(error=ProviderUnavailableError("down"))
    out = tmp_path / "run.jsonl"
    run(runner.load_cases(ids={"p4"}), fake, out)
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["error"].startswith("provider_unavailable") and "output" not in row


def test_budget_stops_new_cases(tmp_path: Path):
    fake = FakeProvider(model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0)  # $4 per case
    budget = run(runner.load_cases(ids={"p2", "p4", "p5"}), fake, tmp_path / "run.jsonl", limit=5.0)
    assert len(fake.calls) == 2 and len(budget.skipped) == 1


# --- Reporting ---------------------------------------------------------------


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def row(pid: str, mode: str = "normal", auto: dict | None = None, **extra: object) -> dict:
    return {"prompt_id": pid, "category": "c", "mode": mode, "latency_s": 1.0, "cost_usd": 0.01,
            "usage": {"input_tokens": 10, "output_tokens": 5}, "auto": auto, **extra}


def test_verdict_combines_manual_grade_and_auto_checks():
    grades = {"p1": {"pass": True}, "p2": {"pass": True}, "p3": {"pass": False}}
    assert runner.verdict(row("p1"), grades) is True
    assert runner.verdict(row("p2", "brief", {"pass": False}), grades) is False  # auto-check overrides
    assert runner.verdict(row("p3"), grades) is False
    assert runner.verdict(row("p4"), grades) is None  # not graded yet
    assert runner.verdict(row("p5", "brief", {"pass": True}), grades) is True  # auto only
    assert runner.verdict({"prompt_id": "p6", "error": "x"}, grades) is None


def test_report_table_and_totals(tmp_path: Path):
    results = tmp_path / "run.jsonl"
    write_rows(results, [row("p2", "brief", {"pass": True, "sentences": 1, "markdown": False}), row("p10"), row("p4")])
    results.with_suffix(".grades.json").write_text(
        json.dumps({"p4": {"pass": False, "reason": "said $0.10"}, "p10": {"pass": True, "reason": "ok"}}), encoding="utf-8"
    )
    text = runner.report(results)
    lines = text.splitlines()
    assert [line.split("|")[1].strip() for line in lines if line.startswith("| p")] == ["p2", "p4", "p10"]
    assert "said $0.10" in text
    assert "Passed 2/3 graded" in text and "total cost $0.03" in text
