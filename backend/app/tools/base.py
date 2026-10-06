"""The tool interface and the result types.

Nothing here knows about the LLM, the agent loop, or any transport (MCP, HTTP, ...).
A tool is a name, a description, a JSON Schema for its arguments, and execute().
"""
import copy
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar


class ToolError(Exception):
    """An expected failure raised inside a tool (file missing, ERP down, ...).

    The dispatcher turns it into a failed ToolResult. `error_type` is a stable
    machine-readable label; `retryable` tells the recovery layer whether trying
    again could plausibly help.
    """

    def __init__(self, message: str, error_type: str = "tool_error", retryable: bool = False):
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


@dataclass(frozen=True)
class ToolResult:
    """What every tool call returns, whether it worked or not.

    success    the tool ran and did its job. A verification that finds a mismatch is
               still success=True: the verdict lives in `output`.
    tool_name  the tool that was called (even if it turned out not to exist).
    output     JSON-serialisable data on success, None on failure.
    error      human-readable message on failure, None on success.
    metadata   duration_ms always; error_type (and retryable, if relevant) on failure.
    """

    success: bool
    tool_name: str
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Tool:
    """Base class for every tool.

    Subclasses set three class attributes and implement execute():

      name          unique identifier
      description   what the tool does, written for the LLM that will choose it
      input_schema  JSON Schema (type "object") describing the arguments

    execute() receives the arguments as keyword arguments, already validated against
    input_schema by the dispatcher. It returns JSON-serialisable output or raises
    ToolError. Call tools through the ToolDispatcher, not directly.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[dict[str, Any]]

    def execute(self, **arguments: Any) -> Any:
        raise NotImplementedError(f"{type(self).__name__} must implement execute()")

    def spec(self) -> dict[str, Any]:
        """The tool as plain data: what an LLM prompt, an API route, or an MCP adapter needs.

        Maps one-to-one onto an MCP `tools/list` entry (input_schema is MCP's inputSchema).
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": copy.deepcopy(self.input_schema),
        }
