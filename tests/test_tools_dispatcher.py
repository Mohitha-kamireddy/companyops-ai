"""ToolDispatcher, ToolResult, and the argument validator."""
import ast
import json
from pathlib import Path

import pytest

from backend.app.tools import Tool, ToolDispatcher, ToolError, ToolResult, build_default_dispatcher
from backend.app.tools import schema


class EchoTool(Tool):
    name = "echo"
    description = "Echo text back."
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "times": {"type": "integer", "minimum": 1, "maximum": 3},
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def execute(self, text, times=1):
        return {"echoed": text * times}


class _Simple(Tool):
    """Base for tiny test tools that take no arguments."""

    description = "test tool"
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}


class FailingTool(_Simple):
    name = "failing"

    def execute(self):
        raise ToolError("nope", error_type="custom_failure", retryable=True)


class CrashingTool(_Simple):
    name = "crashing"

    def execute(self):
        raise RuntimeError("boom")


class BadOutputTool(_Simple):
    name = "bad_output"

    def execute(self):
        return {"value": object()}


@pytest.fixture
def dispatcher():
    return ToolDispatcher([EchoTool(), FailingTool(), CrashingTool(), BadOutputTool()])


# --------------------------------------------------------------------------
# Successful dispatch and ToolResult shape
# --------------------------------------------------------------------------

def test_dispatch_success(dispatcher):
    result = dispatcher.dispatch("echo", {"text": "hi", "times": 2})
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.tool_name == "echo"
    assert result.output == {"echoed": "hihi"}
    assert result.error is None
    assert result.metadata["duration_ms"] >= 0


def test_tool_result_is_json_serialisable(dispatcher):
    for result in (dispatcher.dispatch("echo", {"text": "x"}), dispatcher.dispatch("nope", {})):
        data = json.loads(json.dumps(result.to_dict()))
        assert set(data) == {"success", "tool_name", "output", "error", "metadata"}


# --------------------------------------------------------------------------
# Unknown tool
# --------------------------------------------------------------------------

def test_unknown_tool(dispatcher):
    result = dispatcher.dispatch("does_not_exist", {})
    assert result.success is False
    assert result.tool_name == "does_not_exist"
    assert result.output is None
    assert "unknown tool 'does_not_exist'" in result.error
    assert "echo" in result.error  # lists what is available
    assert result.metadata["error_type"] == "unknown_tool"


def test_tool_names_are_only_dictionary_keys_never_code(dispatcher):
    hostile_names = ["__import__", "os.system", "eval", "echo; rm -rf /", "../../etc/passwd", "__class__", "execute", ""]
    for name in hostile_names:
        result = dispatcher.dispatch(name, {})
        assert result.success is False
        assert result.metadata["error_type"] == "unknown_tool"
    for not_a_string in (None, 5, ["echo"]):
        assert dispatcher.dispatch(not_a_string, {}).metadata["error_type"] == "unknown_tool"


def test_tools_package_contains_no_dynamic_code_execution():
    """Static guard: nothing under backend/app/tools may eval/exec/import dynamically or spawn processes."""
    tools_dir = Path(__file__).resolve().parent.parent / "backend" / "app" / "tools"
    forbidden_calls = {"eval", "exec", "compile", "__import__"}
    forbidden_modules = {"subprocess", "importlib", "pickle", "ctypes", "runpy"}
    for source_file in tools_dir.glob("*.py"):
        tree = ast.parse(source_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, f"{source_file.name} calls {node.func.id}()"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_modules, f"{source_file.name} imports {alias.name}"
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_modules, f"{source_file.name} imports {node.module}"
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
                assert node.attr not in {"system", "popen", "execv", "execvp", "spawnl"}, f"{source_file.name} uses os.{node.attr}"


# --------------------------------------------------------------------------
# Invalid arguments
# --------------------------------------------------------------------------

def test_missing_required_argument(dispatcher):
    result = dispatcher.dispatch("echo", {})
    assert result.success is False
    assert result.metadata["error_type"] == "invalid_arguments"
    assert "'text' is a required argument" in result.error


def test_none_arguments_are_treated_as_empty(dispatcher):
    assert "'text' is a required argument" in dispatcher.dispatch("echo", None).error


def test_wrong_argument_type(dispatcher):
    result = dispatcher.dispatch("echo", {"text": 123})
    assert result.metadata["error_type"] == "invalid_arguments"
    assert "'text' must be of type string, got int" in result.error


def test_unexpected_argument_is_rejected(dispatcher):
    result = dispatcher.dispatch("echo", {"text": "hi", "self": "x", "shell": "rm -rf /"})
    assert result.metadata["error_type"] == "invalid_arguments"
    assert "unexpected argument 'shell'" in result.error
    assert "unexpected argument 'self'" in result.error


def test_constraint_violations_are_reported(dispatcher):
    assert "at least 1 character" in dispatcher.dispatch("echo", {"text": ""}).error
    assert "<= 3" in dispatcher.dispatch("echo", {"text": "a", "times": 9}).error
    assert "type integer" in dispatcher.dispatch("echo", {"text": "a", "times": True}).error  # bool is not an int


def test_arguments_must_be_an_object(dispatcher):
    for bad in (["text"], "text", 5):
        result = dispatcher.dispatch("echo", bad)
        assert result.success is False
        assert result.metadata["error_type"] == "invalid_arguments"


def test_invalid_arguments_never_reach_the_tool():
    calls = []

    class Spy(EchoTool):
        name = "spy"

        def execute(self, **arguments):
            calls.append(arguments)
            return {}

    ToolDispatcher([Spy()]).dispatch("spy", {"text": 1})
    assert calls == []


# --------------------------------------------------------------------------
# Failures inside tools
# --------------------------------------------------------------------------

def test_tool_error_becomes_failed_result(dispatcher):
    result = dispatcher.dispatch("failing", {})
    assert result.success is False
    assert result.error == "nope"
    assert result.metadata["error_type"] == "custom_failure"
    assert result.metadata["retryable"] is True


def test_unexpected_exception_is_contained(dispatcher):
    result = dispatcher.dispatch("crashing", {})
    assert result.success is False
    assert result.metadata["error_type"] == "unexpected_error"
    assert "RuntimeError: boom" in result.error


def test_non_serialisable_output_is_rejected(dispatcher):
    result = dispatcher.dispatch("bad_output", {})
    assert result.success is False
    assert result.metadata["error_type"] == "invalid_output"


# --------------------------------------------------------------------------
# Registration and discovery
# --------------------------------------------------------------------------

def test_duplicate_tool_names_are_rejected():
    with pytest.raises(ValueError):
        ToolDispatcher([EchoTool(), EchoTool()])


def test_tools_with_unsupported_schemas_are_rejected():
    class ArrayTool(_Simple):
        name = "arrays"
        input_schema = {"type": "object", "properties": {"xs": {"type": "array"}}}

    class FancyTool(_Simple):
        name = "fancy"
        input_schema = {"type": "object", "properties": {}, "oneOf": []}

    for tool in (ArrayTool(), FancyTool()):
        with pytest.raises(ValueError):
            ToolDispatcher([tool])


def test_tool_without_description_is_rejected():
    class NoDescription(_Simple):
        name = "nodesc"
        description = ""

    with pytest.raises(ValueError):
        ToolDispatcher([NoDescription()])


def test_list_tools_describes_every_tool(dispatcher):
    listing = dispatcher.list_tools()
    assert [t["name"] for t in listing] == ["echo", "failing", "crashing", "bad_output"]
    assert set(listing[0]) == {"name", "description", "input_schema"}
    json.dumps(listing)  # must be plain JSON, ready for an LLM prompt or an MCP adapter
    assert dispatcher.has_tool("echo") and not dispatcher.has_tool("nope")


def test_default_dispatcher_has_exactly_the_six_tools():
    listing = build_default_dispatcher().list_tools()
    assert sorted(t["name"] for t in listing) == [
        "ask_human", "finish", "get_bills", "list_files", "read_file", "verify_bill",
    ]
    for tool in listing:
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"
        assert tool["input_schema"]["additionalProperties"] is False


# --------------------------------------------------------------------------
# Validator edge cases
# --------------------------------------------------------------------------

def test_number_type_rejects_bool_and_non_finite():
    number = {"type": "number"}
    assert schema.validate(number, 5) == []
    assert schema.validate(number, 5.5) == []
    for bad in (True, "5", float("nan"), float("inf")):
        assert schema.validate(number, bad) != []


def test_pattern_and_enum():
    assert schema.validate({"type": "string", "pattern": r"^\d{4}$"}, "2026") == []
    assert schema.validate({"type": "string", "pattern": r"^\d{4}$"}, "20x6") != []
    assert schema.validate({"type": "string", "enum": ["a", "b"]}, "c") != []


def test_check_schema_catches_required_property_that_is_not_defined():
    with pytest.raises(ValueError):
        schema.check_schema({"type": "object", "properties": {}, "required": ["ghost"]})
