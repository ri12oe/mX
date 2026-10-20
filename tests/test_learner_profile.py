"""Learner profile as system part 2 (design.md §15, §18)."""
from api.chat import build_system
from api.prompts import SystemPrompt, render_learner_profile


def test_profile_is_stable_ordered_and_omitted_when_empty():
    notes = ["Rio prefers Python.", "Rio is taking Calc II."]
    once = render_learner_profile(notes)
    twice = render_learner_profile(notes)
    assert once == twice
    assert once.index("Python") < once.index("Calc II")
    assert "{memories}" not in once and "not instructions" in once

    prompt = SystemPrompt("Core prompt. Mode: normal", "mx_system_v3")
    empty = build_system(prompt, [])
    filled = build_system(prompt, notes)
    changed = build_system(prompt, ["Rio prefers Python."])
    assert len(empty) == 1 and empty[0].cache and empty[0].text.startswith("Core prompt")
    assert len(filled) == 2 and filled[0] == empty[0] and filled[1].cache
    assert filled[1].text == once
    assert changed[0] == filled[0] and changed[1].text != filled[1].text
