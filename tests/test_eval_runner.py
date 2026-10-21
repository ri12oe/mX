"""evals/run.py with the FakeProvider (no cost)."""
import asyncio
import json
from pathlib import Path

import pytest

from api.config import settings
from evals import run as runner
from providers.base import Citation, ToolStep
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
        if case.tools:
            assert messages[-1].content == case.prompt
        else:  # same tools-off note as /chat
            assert messages[-1].content.startswith(case.prompt + "\n\n(Note from the mX app")


def test_tool_eval_cases_declare_the_checks_from_the_design():
    cases = {c.id: c for c in runner.load_cases()}
    assert "code_execution" in cases["p51"].expect_tools
    assert cases["p54"].expect_citations is True and "web_search" in cases["p54"].expect_tools
    assert cases["p57"].expect_no_tools is True
    assert cases["p59"].tools is False and cases["p59"].expect_no_tools is True
    assert cases["p60"].category == "injection"
    assert cases["p63"].expect_memory_proposal is True
    assert cases["p65"].expect_memory_proposal is False
    assert cases["p67"].memories == ("Rio prefers Python.",)


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


def case(**kwargs: object) -> runner.EvalCase:
    raw: dict[str, object] = {"id": "x", "category": "c", "prompt": "p", "expect": "e"}
    raw.update(kwargs)
    return runner.EvalCase(**raw)  # type: ignore[arg-type]


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
    assert runner.auto_checks(text, case(mode="brief"), [], [])["pass"] is passes  # type: ignore[index]


def test_normal_mode_has_no_auto_checks():
    assert runner.auto_checks("**anything**", case(), [], []) is None


def test_tool_auto_checks():
    code = ToolStep(id="t", tool="code_execution", status="ok", input={"code": "1"})
    cited = [Citation("https://example.com", "Example")]
    assert runner.auto_checks("ok", case(expect_tools=("code_execution",)), [code], [])["pass"] is True
    missed = runner.auto_checks("ok", case(expect_tools=("web_search",)), [code], [])
    assert missed is not None and missed["pass"] is False and missed["tools"] is False
    assert runner.auto_checks("ok", case(expect_no_tools=True), [], [])["pass"] is True
    assert runner.auto_checks("ok", case(expect_no_tools=True), [code], [])["pass"] is False
    assert runner.auto_checks("ok", case(expect_citations=True), [], cited)["pass"] is True
    assert runner.auto_checks("ok", case(expect_citations=True), [], [])["pass"] is False
    proposed = ToolStep(id="m", tool="propose_memory", status="ok", input={"text": "Rio prefers Python."})
    assert runner.auto_checks("ok", case(expect_memory_proposal=True), [proposed], [])["pass"] is True
    assert runner.auto_checks("ok", case(expect_memory_proposal=False), [proposed], [])["pass"] is False


def test_searched_sources_count_when_the_answer_has_no_citation_blocks():
    """Dynamic filtering often returns answers without citation blocks (task 16 live test)."""
    searched = ToolStep(id="s", tool="web_search", status="ok", input={"query": "q"},
                        output={"sources": [{"url": "https://python.org", "title": "Python"}]})
    failed = ToolStep(id="f", tool="web_search", status="error", input={"query": "q"}, error_code="unavailable")
    assert runner.auto_checks("ok", case(expect_citations=True), [searched], [])["pass"] is True
    assert runner.auto_checks("ok", case(expect_citations=True), [failed], [])["pass"] is False
    empty_search = ToolStep(id="e", tool="web_search", status="ok", input={"query": "q"}, output={"sources": []})
    assert runner.auto_checks("ok", case(expect_citations=True), [empty_search], [])["pass"] is False


def test_an_empty_reply_fails_even_a_hand_graded_case():
    """Eval p59 (2026-10-20) passed "no tools used" with an empty reply."""
    result = runner.auto_checks("   ", case(expect_no_tools=True), [], [])
    assert result == {"answered": False, "no_tools": True, "pass": False}
    assert runner.auto_checks("", case(), [], []) == {"answered": False, "pass": False}
    assert runner.auto_checks("A real answer.", case(), [], []) is None  # still graded by hand
    assert runner.auto_reason({"answered": False, "pass": False}) == "empty reply"


def test_tools_off_cases_get_the_same_note_as_chat():
    off = runner.build_messages(case(tools=False))
    on = runner.build_messages(case())
    assert "are off for this message" in off[-1].content
    assert "are off for this message" not in on[-1].content


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
    assert (p2["output"], p2["model"], p2["prompt_version"]) == ("It is Tokyo.", "claude-opus-5-5", "mx_system_v5")
    assert p2["usage"]["input_tokens"] == 1000 and p2["usage"]["output_tokens"] == 100
    assert p2["usage"]["web_searches"] == 0 and p2["tool_steps"] == []
    assert p2["cost_usd"] == pytest.approx(0.006)
    assert p2["auto"]["pass"] is True and rows["p4"]["auto"] is None


def test_run_uses_the_same_prompt_and_mode_options_as_chat(tmp_path: Path):
    fake = FakeProvider()
    run(runner.load_cases(ids={"p2"}), fake, tmp_path / "run.jsonl")
    call = fake.calls[0]
    assert call.method == "generate"
    assert "Mode: brief" in call.system[0].text and call.system[0].cache is True
    assert call.opts["max_tokens"] == 2048 and call.opts["effort"] == "low"
    assert call.opts["cache_messages"] is True and call.opts["tools"].enabled is True


def test_tool_case_records_steps_citations_and_the_search_fee(tmp_path: Path):
    step = ToolStep(
        id="s", tool="web_search", status="ok", input={"query": "python"},
        output={"sources": [{"url": "https://python.org", "title": "Python"}]},
    )
    fake = FakeProvider(
        script=["3.14 is current."], citations=[Citation("https://python.org", "Python")],
        model="claude-opus-5-5", input_tokens=1000, output_tokens=100,
    )
    # The step has to be in the script so generate records it.
    fake.script = ["3.14 is current.", step]
    out = tmp_path / "run.jsonl"
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"id":"t1","category":"tools_search","prompt":"version?","expect":"cites",'
        '"expect_tools":["web_search"],"expect_citations":true}\n',
        encoding="utf-8",
    )
    run(runner.load_cases(path), fake, out)
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["tool_steps"][0]["tool"] == "web_search"
    assert row["citations"] == [{"url": "https://python.org", "title": "Python"}]
    assert row["usage"]["web_searches"] == 1
    assert row["cost_usd"] == pytest.approx(0.006 + 0.01)  # tokens plus the search fee
    assert row["auto"]["pass"] is True
    assert fake.calls[0].opts["tools"].web_search is True


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


# --- Loading edge cases --------------------------------------------------------


def test_load_cases_skips_blank_lines_and_names_a_bad_line(tmp_path: Path):
    good = '{"id": "a", "category": "c", "prompt": "p", "expect": "e"}'
    path = tmp_path / "prompts.jsonl"
    path.write_text(f"{good}\n\n", encoding="utf-8")
    assert [c.id for c in runner.load_cases(path)] == ["a"]

    path.write_text(f"{good}\n\n{{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 3"):
        runner.load_cases(path)


def test_load_image_rejects_non_images(tmp_path: Path):
    path = tmp_path / "notes.png"
    path.write_bytes(b"just text")
    with pytest.raises(ValueError, match="not a JPEG, PNG, GIF, or WebP"):
        runner.load_image(path)


def test_report_explains_failed_auto_checks(tmp_path: Path):
    results = tmp_path / "run.jsonl"
    write_rows(results, [row("p2", "brief", {"pass": False, "sentences": 3, "markdown": False})])
    assert "auto: 3 sentences, markdown=False" in runner.report(results)


# --- Command line ----------------------------------------------------------------


def use_fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake: FakeProvider) -> None:
    monkeypatch.setattr(runner, "create_provider", lambda *args, **kwargs: fake)
    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)


def test_main_dry_run_lists_cases_without_calling_the_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
):
    fake = FakeProvider()
    use_fake(monkeypatch, tmp_path, fake)
    assert runner.main(["--dry-run", "--ids", "p2,p19,p21"]) == 0
    out = capsys.readouterr().out
    assert "3 cases" in out and "+1 image(s)" in out and "+2 history" in out
    assert fake.calls == [] and list(tmp_path.iterdir()) == []


def test_main_runs_writes_results_and_prints_the_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
):
    use_fake(monkeypatch, tmp_path, FakeProvider(chunks=["It is Tokyo."], model="claude-opus-5-5"))
    assert runner.main(["--ids", "p2,p4"]) == 0
    files = list(tmp_path.glob("*_mx_system_v5.jsonl"))
    assert len(files) == 1 and len(files[0].read_text(encoding="utf-8").splitlines()) == 2
    out = capsys.readouterr().out
    assert "Wrote 2 rows" in out and "| p2 |" in out and "Passed 1/1 graded" in out


def test_main_reports_cases_skipped_by_the_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
):
    fake = FakeProvider(model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0)  # $4 per case
    use_fake(monkeypatch, tmp_path, fake)
    runner.main(["--ids", "p2,p4,p5", "--max-cost", "5", "--concurrency", "1"])
    assert "Budget reached: skipped" in capsys.readouterr().out
    assert len(fake.calls) == 2


def test_main_report_mode_prints_an_existing_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    results = tmp_path / "run.jsonl"
    write_rows(results, [row("p4")])
    assert runner.main(["--report", str(results)]) == 0
    assert "| p4 |" in capsys.readouterr().out
