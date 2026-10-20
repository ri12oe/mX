"""Client tools mX runs itself (design.md §17, §18).

The only one in Phase 2 is propose_memory. It validates a note and returns
fixed text to the model. It does not write to the database: a memory exists
only after Rio saves it.
"""
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from api.db import MEMORY_TEXT_MAX
from api.prompts import load_prompt_file
from providers.base import ClientTool, ClientToolResult

DESCRIPTION_FILE = "prompts/tools/propose_memory.md"
RESULT_FILE = "prompts/tools/propose_memory_result.md"
MAX_ACCEPTED_PER_TURN = 1

INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"text": {"type": "string", "maxLength": MEMORY_TEXT_MAX}},
    "required": ["text"],
    "additionalProperties": False,
}


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(min_length=1, max_length=MEMORY_TEXT_MAX)

    def cleaned(self) -> str:
        return self.text.strip()


def propose_memory_tool() -> ClientTool:
    """One tool instance per turn, so the one-proposal cap resets every message."""
    accepted = 0

    def run(raw: dict[str, object]) -> ClientToolResult:
        nonlocal accepted
        try:
            text = _Proposal.model_validate(raw).cleaned()
        except ValidationError:
            return ClientToolResult("That isn't a usable memory.", is_error=True)
        if not text or len(text) > MEMORY_TEXT_MAX:
            return ClientToolResult("That isn't a usable memory.", is_error=True)
        if accepted >= MAX_ACCEPTED_PER_TURN:
            return ClientToolResult("limit reached", is_error=True)
        accepted += 1
        return ClientToolResult(load_prompt_file(RESULT_FILE))

    return ClientTool(
        name="propose_memory",
        description=load_prompt_file(DESCRIPTION_FILE),
        input_schema=INPUT_SCHEMA,
        run=run,
    )
