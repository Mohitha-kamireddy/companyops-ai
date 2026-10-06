"""ToolDispatcher: the single entry point for running tools.

    dispatch(tool_name, arguments) -> ToolResult

It never raises for problems with the *call* (unknown tool, bad arguments, tool failure);
it always returns a ToolResult so the agent loop can observe the failure and adapt.

There is deliberately no way to run arbitrary code through here. A tool name is only ever
used as a key into a dict of tool instances registered at construction time. It is never
imported, evaluated, or looked up with getattr.
"""
import json
import logging
import time
from collections.abc import Iterable
from typing import Any

from backend.app.tools import schema as schema_lib
from backend.app.tools.base import Tool, ToolError, ToolResult

logger = logging.getLogger(__name__)


class ToolDispatcher:
    def __init__(self, tools: Iterable[Tool]):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self._register(tool)

    def _register(self, tool: Tool) -> None:
        if not isinstance(tool.name, str) or not tool.name:
            raise ValueError(f"{type(tool).__name__} must define a non-empty name")
        if not isinstance(tool.description, str) or not tool.description:
            raise ValueError(f"tool '{tool.name}' must define a description")
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name '{tool.name}'")
        schema_lib.check_schema(tool.input_schema, f"input_schema of tool '{tool.name}'")
        if tool.input_schema["type"] != "object":
            raise ValueError(f"input_schema of tool '{tool.name}' must have type 'object'")
        self._tools[tool.name] = tool

    # ------------------------------------------------------------------
    # Discovery (what an LLM prompt, an API route, or a future MCP adapter needs)
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        """Name, description, and input schema of every registered tool."""
        return [tool.spec() for tool in self._tools.values()]

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._tools

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def dispatch(self, tool_name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        """Validate and run one tool call. Always returns a ToolResult."""
        started = time.perf_counter()

        def failure(error: str, error_type: str, **extra: Any) -> ToolResult:
            metadata = {
                "error_type": error_type,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                **extra,
            }
            return ToolResult(success=False, tool_name=tool_name, error=error, metadata=metadata)

        # 1. The tool must exist.
        tool = self._tools.get(tool_name) if isinstance(tool_name, str) else None
        if tool is None:
            available = ", ".join(sorted(self._tools))
            return failure(f"unknown tool '{tool_name}'. Available tools: {available}", "unknown_tool")

        # 2. The arguments must be an object that satisfies the tool's schema.
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return failure("tool arguments must be a JSON object", "invalid_arguments")
        problems = schema_lib.validate(tool.input_schema, arguments)
        if problems:
            return failure("invalid arguments: " + "; ".join(problems), "invalid_arguments")

        # 3. Run it.
        try:
            output = tool.execute(**arguments)
        except ToolError as exc:
            return failure(str(exc), exc.error_type, retryable=exc.retryable)
        except Exception as exc:  # a buggy tool must not crash the agent loop
            logger.exception("tool '%s' raised an unexpected error", tool_name)
            return failure(f"unexpected error in tool '{tool_name}': {type(exc).__name__}: {exc}", "unexpected_error")

        # 4. Output must be JSON-serialisable (it goes into agent state and the audit log).
        try:
            json.dumps(output)
        except (TypeError, ValueError) as exc:
            return failure(f"tool '{tool_name}' returned output that is not JSON-serialisable: {exc}", "invalid_output")

        return ToolResult(
            success=True,
            tool_name=tool_name,
            output=output,
            metadata={"duration_ms": round((time.perf_counter() - started) * 1000, 2)},
        )
