from pathlib import Path

import pytest

from api.config import settings
from api.prompts import MODE_OPTIONS, MODES, check_mode, load_system_prompt


def write_prompt(tmp_path: Path, text: str, name: str = "test_prompt_v2.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_mode_is_filled_in(tmp_path: Path):
    path = write_prompt(tmp_path, "You are mX.\nMode: {mode}")
    assert load_system_prompt("brief", path).text == "You are mX.\nMode: brief"


def test_every_placeholder_is_replaced(tmp_path: Path):
    path = write_prompt(tmp_path, "Mode: {mode}. Remember, {mode} mode.")
    assert load_system_prompt("normal", path).text == "Mode: normal. Remember, normal mode."


def test_comments_are_stripped(tmp_path: Path):
    path = write_prompt(tmp_path, "<!-- draft notes -->\nHello {mode}<!-- inline\nmultiline -->!")
    assert load_system_prompt("normal", path).text == "Hello normal!"


def test_curly_braces_in_code_examples_are_safe(tmp_path: Path):
    """str.format would crash on these; str.replace leaves them alone."""
    path = write_prompt(tmp_path, "Example: const obj = { a: 1 }; f'{x}'\nMode: {mode}")
    text = load_system_prompt("normal", path).text
    assert "const obj = { a: 1 }; f'{x}'" in text


def test_version_is_the_file_name(tmp_path: Path):
    path = write_prompt(tmp_path, "Mode: {mode}", name="mx_system_v7.md")
    assert load_system_prompt("normal", path).version == "mx_system_v7"


def test_invalid_mode_is_rejected(tmp_path: Path):
    path = write_prompt(tmp_path, "Mode: {mode}")
    with pytest.raises(ValueError, match="mode"):
        load_system_prompt("loud", path)


def test_missing_placeholder_is_an_error(tmp_path: Path):
    path = write_prompt(tmp_path, "No placeholder here.")
    with pytest.raises(ValueError, match="placeholder"):
        load_system_prompt("normal", path)


def test_edits_apply_without_restart(tmp_path: Path):
    path = write_prompt(tmp_path, "v1 {mode}")
    assert load_system_prompt("normal", path).text == "v1 normal"
    path.write_text("v2 {mode}", encoding="utf-8")
    assert load_system_prompt("normal", path).text == "v2 normal"


def test_real_mx_prompt_loads_in_both_modes():
    normal = load_system_prompt("normal", settings.system_prompt_file)
    brief = load_system_prompt("brief", settings.system_prompt_file)

    assert normal.version == brief.version == "mx_system_v1"
    assert normal.text.startswith("You are mX")
    assert "Mode: normal" in normal.text and "Mode: brief" in brief.text
    assert "<!--" not in normal.text and "{mode}" not in normal.text


def test_mode_options_match_design():
    assert set(MODE_OPTIONS) == set(MODES)
    assert MODE_OPTIONS["normal"] == {"max_tokens": 16000, "effort": "high"}
    assert MODE_OPTIONS["brief"] == {"max_tokens": 2048, "effort": "low"}


def test_check_mode():
    check_mode("normal")
    with pytest.raises(ValueError):
        check_mode("")
