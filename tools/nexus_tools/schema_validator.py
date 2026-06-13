"""Small JSON-schema-style validator for NEXUS tool calls.

The goal is not full JSON Schema compliance. It enforces the parts NEXUS tools
actually publish today: required fields, object properties, primitive types,
arrays, and enums. This catches malformed LLM tool calls before execution.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


class ToolSchemaValidator:
    TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @classmethod
    def validate(cls, schema: Dict[str, Any], params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], List[str]]:
        parameters = schema.get("parameters") if isinstance(schema, dict) else None
        if not isinstance(parameters, dict):
            return True, params, []

        if not isinstance(params, dict):
            return False, {}, ["Tool params must be an object/dict."]

        errors: List[str] = []
        normalized = dict(params)
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])

        if isinstance(required, list):
            for name in required:
                if name not in normalized or normalized.get(name) in (None, ""):
                    errors.append(f"Missing required parameter: {name}")

        if isinstance(properties, dict):
            for name, spec in properties.items():
                if name not in normalized or not isinstance(spec, dict):
                    continue
                value = normalized[name]
                expected = spec.get("type")
                enum = spec.get("enum")
                if enum and value not in enum:
                    errors.append(f"Parameter '{name}' must be one of {enum}; got {value!r}")
                if expected:
                    ok, coerced = cls._coerce_type(value, expected, spec)
                    if ok:
                        normalized[name] = coerced
                    else:
                        errors.append(f"Parameter '{name}' must be {expected}; got {type(value).__name__}")

        return not errors, normalized, errors

    @classmethod
    def _coerce_type(cls, value: Any, expected: str, spec: Dict[str, Any]) -> Tuple[bool, Any]:
        if expected == "integer" and isinstance(value, str):
            try:
                return True, int(value)
            except ValueError:
                return False, value
        if expected == "number" and isinstance(value, str):
            try:
                return True, float(value)
            except ValueError:
                return False, value
        if expected == "boolean" and isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True, True
            if lowered in {"false", "0", "no"}:
                return True, False
            return False, value
        if expected == "array" and not isinstance(value, list):
            return False, value
        if expected == "object" and not isinstance(value, dict):
            return False, value

        py_type = cls.TYPE_MAP.get(expected)
        if py_type is None:
            return True, value
        if expected == "number" and isinstance(value, bool):
            return False, value
        if expected == "integer" and isinstance(value, bool):
            return False, value
        return isinstance(value, py_type), value
