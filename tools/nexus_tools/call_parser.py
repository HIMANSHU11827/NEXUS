"""Unified tool call parser — shared by the agent loop and Hive sub-agents.

Parses tool calls from LLM text output in multiple formats:
- <tool_call>{"tool": "name", "params": {...}}</tool_call>
- ```tool {"tool": "name", "params": {...}} ```
- function(name, {JSON})  — OpenAI legacy
- <function=name>{JSON}   — Anthropic legacy
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# Patterns that the agent loop and hive both recognize
_TOOL_CALL_PATTERNS: List[re.Pattern] = [
    re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S | re.I),
    re.compile(r"```(?:tool|tool_call|json)\s*(\{.*?\})\s*```", re.S | re.I),
    re.compile(r"<tool>\s*(\{.*?\})\s*</tool>", re.S | re.I),
]

# Pattern for function(name, {JSON}) format
_FUNCTION_CALL_RE = re.compile(
    r"(\w+)\s*\(\s*(\{)", re.MULTILINE
)

# Pattern for <function=name>{JSON} format
_FUNCTION_TAG_RE = re.compile(
    r"<function=(\w+)>\s*(\{)", re.I
)


def parse_single_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Extract a single structured tool call from LLM text.

    Accepted forms (first match wins)::

        <tool_call>{"tool": "name", "params": {...}}</tool_call>
        ```tool
        {"tool": "bash", "params": {"command": "ls"}}
        ```
        <tool>{"tool": "reading", "params": {"path": "..."}}</tool>

    Returns a dict ``{"tool": str, "params": dict}`` or None.
    """
    if not text:
        return None
    for pattern in _TOOL_CALL_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            data = json.loads(match.group(1))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("tool") or data.get("name") or data.get("tool_name")
        if not name:
            continue
        params = data.get("params") or data.get("arguments") or data.get("args") or {}
        if not isinstance(params, dict):
            params = {"input": params}
        return {"tool": str(name).lower(), "params": params}
    return None


def parse_all_tool_calls(text: str, known_tools: Optional[set] = None) -> List[Dict[str, Any]]:
    """Parse all tool calls from LLM text output.

    Discovers:
    1. ``<tool_call>`` XML blocks
    2. ``function(name, {JSON})``  OpenAI legacy format
    3. ``<function=name>{JSON}``   Anthropic legacy format

    Args:
        text: LLM output text to scan
        known_tools: Optional set of known tool names to filter against

    Returns:
        List of ``{"tool": str, "params": dict}`` dicts
    """
    found: List[Dict[str, Any]] = []
    known = known_tools or set()

    # 1. XML <tool_call> blocks
    for pattern in _TOOL_CALL_PATTERNS:
        for match in pattern.finditer(text or ""):
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            name = data.get("tool") or data.get("name") or data.get("tool_name")
            if not name:
                continue
            params = data.get("params") or data.get("arguments") or data.get("args") or {}
            if not isinstance(params, dict):
                params = {"input": params}
            found.append({"tool": str(name).lower(), "params": params})

    # 2. function(name, {JSON}) format
    for match in _FUNCTION_CALL_RE.finditer(text or ""):
        name = match.group(1).lower()
        if known and name not in known:
            continue
        start = match.start(2)
        try:
            params, _consumed = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(params, dict):
            found.append({"tool": name, "params": params})

    # 3. <function=name>{JSON} format
    for match in _FUNCTION_TAG_RE.finditer(text or ""):
        name = match.group(1).lower()
        if known and name not in known:
            continue
        start = match.start(2)
        try:
            params, _consumed = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(params, dict):
            found.append({"tool": name, "params": params})

    # Deduplicate by (name, sorted params)
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for call in found:
        sig = (call["tool"], json.dumps(call["params"], sort_keys=True))
        if sig not in seen:
            seen.add(sig)
            unique.append(call)
    return unique
