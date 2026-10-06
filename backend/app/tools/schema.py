"""A small JSON Schema validator for tool arguments, using only the standard library.

Tools declare their inputs as plain JSON Schema (the same format MCP uses). This module
validates arguments against the subset of JSON Schema the tools actually need:

  type (string, number, integer, boolean, object), enum, properties, required,
  additionalProperties (true/false), minLength, maxLength, pattern, minimum, maximum

check_schema() rejects anything outside that subset when a tool is registered, so a tool
can never silently end up with arguments that are not being validated. The `jsonschema`
package could replace this module later without any change to the tools.
"""
import math
import re
from typing import Any

SUPPORTED_TYPES = frozenset({"string", "number", "integer", "boolean", "object"})

SUPPORTED_KEYWORDS = frozenset(
    {
        "type", "enum", "properties", "required", "additionalProperties",
        "minLength", "maxLength", "pattern", "minimum", "maximum",
        "description", "title",  # annotations, not validated
    }
)


def check_schema(schema: Any, where: str = "schema") -> None:
    """Raise ValueError if the schema is malformed or uses something validate() can't enforce."""
    if not isinstance(schema, dict):
        raise ValueError(f"{where}: a schema must be a JSON object")

    unsupported = sorted(set(schema) - SUPPORTED_KEYWORDS)
    if unsupported:
        raise ValueError(f"{where}: unsupported JSON Schema keyword(s): {', '.join(unsupported)}")

    type_name = schema.get("type")
    if not isinstance(type_name, str) or type_name not in SUPPORTED_TYPES:
        raise ValueError(f"{where}: 'type' is required and must be one of {sorted(SUPPORTED_TYPES)}, got {type_name!r}")

    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise ValueError(f"{where}: 'enum' must be a non-empty list")

    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError) as exc:
            raise ValueError(f"{where}: invalid 'pattern': {exc}") from None

    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        raise ValueError(f"{where}: 'additionalProperties' must be true or false")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError(f"{where}: 'properties' must be an object")
    for name, sub_schema in properties.items():
        check_schema(sub_schema, f"{where}.properties.{name}")

    required = schema.get("required", [])
    if not isinstance(required, list):
        raise ValueError(f"{where}: 'required' must be a list")
    for name in required:
        if name not in properties:
            raise ValueError(f"{where}: required property {name!r} is not defined in 'properties'")


def validate(schema: dict[str, Any], value: Any) -> list[str]:
    """Check value against schema. Returns human-readable problems; an empty list means valid."""
    problems: list[str] = []
    _validate(schema, value, "", problems)
    return problems


def _validate(schema: dict[str, Any], value: Any, path: str, problems: list[str]) -> None:
    label = f"'{path}'" if path else "value"
    type_name = schema["type"]

    if not _is_type(value, type_name):
        problems.append(f"{label} must be of type {type_name}, got {type(value).__name__}")
        return  # further complaints about a value of the wrong type would only be noise

    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{label} must be one of {schema['enum']}")

    if type_name == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            n = schema["minLength"]
            problems.append(f"{label} must be at least {n} character{'s' if n != 1 else ''} long")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append(f"{label} must be at most {schema['maxLength']} characters long")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            problems.append(f"{label} does not match the required format {schema['pattern']}")

    if type_name in ("number", "integer"):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{label} must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{label} must be <= {schema['maximum']}")

    if type_name == "object":
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                problems.append(f"'{_join(path, name)}' is a required argument")
        for name, item in value.items():
            if name in properties:
                _validate(properties[name], item, _join(path, name), problems)
            elif schema.get("additionalProperties", True) is False:
                allowed = ", ".join(sorted(properties)) or "none"
                problems.append(f"unexpected argument '{_join(path, name)}' (allowed arguments: {allowed})")


def _join(path: str, name: Any) -> str:
    return f"{path}.{name}" if path else str(name)


def _is_type(value: Any, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return isinstance(value, int) or math.isfinite(value)
    if type_name == "object":
        return isinstance(value, dict)
    return False
