"""ask_human and finish: tools that talk to the human or to the agent loop itself."""
from collections.abc import Callable
from typing import Any

from backend.app.tools.base import Tool, ToolError

_YES = {"y", "yes", "approve", "approved"}


class AskHumanTool(Tool):
    name = "ask_human"
    description = (
        "Ask a human operator to approve or reject something before the agent proceeds. "
        "Blocks until the human answers. Returns output.decision, either 'approved' or "
        "'rejected'. Only an explicit yes counts as approval; any other answer is a rejection."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "minLength": 1,
                "description": "What the human is being asked to approve, in plain language.",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    }

    def __init__(self, prompt_fn: Callable[[str], str] | None = None):
        # Terminal input() for now. Injectable so tests (and later an API/UI approval
        # gate) can supply the answer without touching the terminal.
        self._prompt = prompt_fn or input

    def execute(self, question: str) -> dict[str, Any]:
        try:
            answer = self._prompt(f"\n[HUMAN APPROVAL REQUIRED]\n{question}\nApprove? [y/N]: ")
        except EOFError:
            # No terminal attached: fail closed rather than guessing.
            raise ToolError("no interactive terminal available to ask the human", error_type="human_unavailable") from None
        answer = answer.strip()
        return {"decision": "approved" if answer.lower() in _YES else "rejected", "response": answer}


class FinishTool(Tool):
    name = "finish"
    description = (
        "Tell the system you believe the task is done (or cannot be done). This is only a "
        "request to finish: it is NOT proof of completion. The system will independently "
        "verify the result before accepting it."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "minLength": 1,
                "description": "What was done, or why the task could not be completed.",
            },
            "outcome": {
                "type": "string",
                "enum": ["success", "failure"],
                "description": "Whether you believe the goal was achieved. Defaults to 'success'.",
            },
        },
        "required": ["summary"],
        "additionalProperties": False,
    }

    def execute(self, summary: str, outcome: str = "success") -> dict[str, Any]:
        # Records the claim and nothing else. completion_verified is always False here:
        # only the verification layer may decide a run is really complete.
        return {
            "finish_requested": True,
            "claimed_outcome": outcome,
            "summary": summary,
            "completion_verified": False,
        }
