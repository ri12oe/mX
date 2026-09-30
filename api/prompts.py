"""System prompt loading and per-mode settings (design.md §6, §8).

Prompts are data: the text lives in prompts/*.md, never in code.
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

Mode = Literal["normal", "brief"]
MODES: tuple[str, ...] = get_args(Mode)
MODE_PLACEHOLDER = "{mode}"

# How much room and thinking effort each mode gets (design.md §6).
# max_tokens is a ceiling, not a cost; the model's thinking counts toward it.
MODE_OPTIONS: dict[str, dict[str, Any]] = {
    "normal": {"max_tokens": 16000, "effort": "high"},
    "brief": {"max_tokens": 2048, "effort": "low"},
}

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class SystemPrompt:
    text: str
    version: str  # file name without extension, stored in usage.prompt_version


def load_system_prompt(mode: str, path: str | Path) -> SystemPrompt:
    """Read the prompt file, drop <!-- notes -->, and fill in the mode.

    Uses str.replace, not str.format, so `{}` in code examples is safe.
    Read on every call, so prompt edits apply without restarting the server.
    """
    check_mode(mode)
    file = Path(path)
    template = _COMMENT.sub("", file.read_text(encoding="utf-8")).strip()
    if MODE_PLACEHOLDER not in template:
        raise ValueError(f"{file} has no {MODE_PLACEHOLDER} placeholder.")
    return SystemPrompt(text=template.replace(MODE_PLACEHOLDER, mode), version=file.stem)


def check_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}, got {mode!r}")
