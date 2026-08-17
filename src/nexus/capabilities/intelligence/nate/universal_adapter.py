"""
NATE Layer 1: Universal Format Adapter
Write tool definitions once, auto-convert to ANY provider's native format.
No MCP overhead, no protocol translation cost.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional

ProviderType = Literal["openai", "anthropic", "google", "mistral", "ollama", "groq"]


class UniversalTool:
    name: str
    description: str
    parameters: Dict[str, Any]
    required: List[str]

    def __init__(self, name: str, description: str = "", parameters: Optional[Dict[str, Any]] = None, required: Optional[List[str]] = None):
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.required = required or []

    def to_openai(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {**self.parameters, "required": self.required},
            },
        }

    def to_anthropic(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {**self.parameters, "required": self.required},
        }

    def to_google(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {**self.parameters, "required": self.required},
        }

    def to_mistral(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {**self.parameters, "required": self.required},
            },
        }

    def to_ollama(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {**self.parameters, "required": self.required},
            },
        }

    def to_groq(self) -> Dict[str, Any]:
        return self.to_openai()

    def to_provider(self, provider: ProviderType) -> Dict[str, Any]:
        method = getattr(self, f"to_{provider}", None)
        if method:
            return method()
        return self.to_openai()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UniversalTool":
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            parameters=data.get("parameters"),
            required=data.get("required", []),
        )


class UniversalAdapter:
    def __init__(self):
        self._tools: Dict[str, UniversalTool] = {}

    def register(self, tool: UniversalTool) -> None:
        self._tools[tool.name] = tool

    def register_many(self, tools: List[UniversalTool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Optional[UniversalTool]:
        return self._tools.get(name)

    def all(self) -> List[UniversalTool]:
        return list(self._tools.values())

    def convert(self, provider: ProviderType, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        tools = self.all()
        if names:
            tools = [t for t in tools if t.name in names]
        return [t.to_provider(provider) for t in tools]

    def convert_to_openai(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        return self.convert("openai", names)

    def convert_to_anthropic(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        return self.convert("anthropic", names)

    def convert_to_google(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        return self.convert("google", names)

    def count_tokens_before(self, names: Optional[List[str]] = None) -> int:
        tools = self.all()
        if names:
            tools = [t for t in tools if t.name in names]
        raw = json.dumps([t.to_dict() for t in tools])
        return len(raw)

    def count_tokens_after_triple(self, names: Optional[List[str]] = None) -> int:
        tools = self.all()
        if names:
            tools = [t for t in tools if t.name in names]
        compressed = [{"n": t.name, "d": t.description[:50], "p": list(t.parameters.get("properties", {}).keys())} for t in tools]
        return len(json.dumps(compressed))
