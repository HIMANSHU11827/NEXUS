"""Security boundaries shared by NEXUS MCP transports and servers."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, TextIO, Tuple

MAX_RESULT_LIMIT = 200
MAX_INDEX_FILES = 50_000
MAX_MCP_LINE_CHARS = 1_048_576

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b"),
)


def redact_secret_text(value: str) -> str:
    """Best-effort redaction for untrusted MCP process diagnostics."""
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]", redacted)
    return redacted


def read_bounded_line(stream: TextIO, maximum: int = MAX_MCP_LINE_CHARS) -> Tuple[str, bool]:
    """Read one newline-delimited MCP message without unbounded allocation."""
    line = stream.readline(maximum + 1)
    oversized = len(line) > maximum
    if oversized and not line.endswith("\n"):
        while True:
            remainder = stream.readline(maximum + 1)
            if not remainder or remainder.endswith("\n"):
                break
    return line if not oversized else "", oversized


def workspace_root(arguments: Dict[str, Any]) -> str:
    """Resolve a requested root without escaping the configured workspace."""
    allowed = Path(os.environ.get("NEXUS_MCP_ALLOWED_ROOT", os.getcwd())).resolve()
    requested = Path(str(arguments.get("root") or allowed))
    if not requested.is_absolute():
        requested = allowed / requested
    resolved = requested.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ValueError("Requested root is outside NEXUS_MCP_ALLOWED_ROOT") from exc
    if not resolved.is_dir():
        raise ValueError("Requested root must be an existing directory")
    return str(resolved)


def bounded_int(arguments: Dict[str, Any], name: str, default: int, maximum: int) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= parsed <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return parsed
