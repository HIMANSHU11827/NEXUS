"""Canonical structured result envelope for the NEXUS tool-calling lifecycle.

Every tool invocation routed through :class:`~tools.nexus_tools.registry.ToolRegistry`
is normalized into a :class:`ToolCallResult`.

Backwards compatibility is a hard requirement: ``ToolCallResult`` subclasses the
legacy :class:`~tools.nexus_tools.base_tool.ToolResult`, so existing callers that
do ``isinstance(item, ToolResult)`` / ``item.success`` / ``item.output`` /
``item.error`` keep working unchanged.  In addition the object is dict-compatible
(``result["status"]``, ``result.get(...)``, ``dict(result.to_dict())``) so newer
callers can consume the canonical envelope:

    tool_call_id, name, status(ok|error|timeout|unimplemented|blocked),
    started_at, finished_at, duration_ms, data, stdout, stderr,
    error{type,message,retryable}, metadata
"""

from __future__ import annotations

import ast
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from tools.nexus_tools.base_tool import ToolResult

# Status vocabulary
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"
STATUS_UNIMPLEMENTED = "unimplemented"
STATUS_BLOCKED = "blocked"

VALID_STATUSES = {STATUS_OK, STATUS_ERROR, STATUS_TIMEOUT, STATUS_UNIMPLEMENTED, STATUS_BLOCKED}

#: Default cap for captured tool output (characters).  Tools that stream
#: gigabytes of stdout must not be able to blow up the agent context or RAM.
DEFAULT_MAX_OUTPUT_CHARS = 200_000

#: Error types that are worth retrying automatically.
RETRYABLE_ERROR_TYPES = {
    "TimeoutError",
    "asyncio.TimeoutError",
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionAbortedError",
    "ConnectionRefusedError",
    "BrokenPipeError",
    "TimeoutExpired",
    "OSError",
    "IOError",
    "HTTPError",
    "ClientError",
    "ServerError",
    "RateLimitError",
}

#: Error types that are definitely NOT retryable (bad input / programming error).
NON_RETRYABLE_ERROR_TYPES = {
    "ValueError",
    "TypeError",
    "KeyError",
    "AttributeError",
    "IndexError",
    "NotImplementedError",
    "PermissionError",
    "FileNotFoundError",
    "NotADirectoryError",
    "IsADirectoryError",
    "ZeroDivisionError",
    "AssertionError",
    "SyntaxError",
    "ImportError",
    "ModuleNotFoundError",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_error(exc: BaseException) -> Dict[str, Any]:
    """Classify an exception into ``{type, message, retryable}``."""
    name = type(exc).__name__
    if isinstance(exc, TimeoutError):
        retryable = True
    elif name in NON_RETRYABLE_ERROR_TYPES:
        retryable = False
    elif name in RETRYABLE_ERROR_TYPES:
        retryable = True
    elif isinstance(exc, (ConnectionError, OSError)):
        retryable = True
    else:
        retryable = False
    message = str(exc) or name
    return {"type": name, "message": message[:4000], "retryable": retryable}


def truncate_output(text: str, limit: int = DEFAULT_MAX_OUTPUT_CHARS) -> "tuple[str, bool]":
    """Bound an output string. Returns ``(text, truncated)``."""
    if limit is None or limit <= 0 or len(text) <= limit:
        return text, False
    head = limit // 2
    tail = limit - head
    marker = f"\n\n...[TRUNCATED {len(text) - limit} of {len(text)} chars]...\n\n"
    return text[:head] + marker + text[-tail:], True


@dataclass
class ToolCallResult(ToolResult):
    """Canonical, dict-compatible tool result envelope."""

    tool_call_id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:16]}")
    name: str = ""
    status: str = STATUS_OK
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    data: Any = None
    stdout: str = ""
    stderr: str = ""
    error_info: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            self.status = STATUS_ERROR
        # Keep the legacy fields in sync with the canonical ones.
        self.success = self.status == STATUS_OK
        if not self.output and self.stdout:
            self.output = self.stdout
        elif self.output and not self.stdout:
            self.stdout = self.output
        if self.error_info and not self.error:
            self.error = str(self.error_info.get("message") or "")
        if self.error and not self.stderr:
            self.stderr = self.error

    # ── dict compatibility ────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "status": self.status,
            "success": self.success,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "data": self.data,
            "output": self.output,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error_info,
            "metadata": self.metadata,
        }

    def keys(self):
        return self.to_dict().keys()

    def __getitem__(self, key: str) -> Any:
        try:
            return self.to_dict()[key]
        except KeyError as exc:
            raise KeyError(key) from exc

    def __contains__(self, key: object) -> bool:
        return key in self.to_dict()

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


def start_envelope(name: str, tool_call_id: Optional[str] = None) -> "tuple[str, str, float]":
    """Return ``(tool_call_id, started_at_iso, monotonic_start)``."""
    return (
        tool_call_id or f"call_{uuid.uuid4().hex[:16]}",
        _now_iso(),
        time.monotonic(),
    )


def finish_envelope(result: ToolCallResult, monotonic_start: float) -> ToolCallResult:
    result.finished_at = _now_iso()
    result.duration_ms = round((time.monotonic() - monotonic_start) * 1000, 3)
    return result


def normalize_result(
    raw: Any,
    *,
    name: str,
    tool_call_id: str,
    started_at: str,
    monotonic_start: float,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
) -> ToolCallResult:
    """Normalize *anything* a tool handler returned into a ToolCallResult.

    Handles: ToolCallResult (passthrough w/ envelope fill), legacy ToolResult,
    dict, None, str, and arbitrary objects.  A handler that returns ``None``
    used to be reported as a silent success with empty output; it is now an
    explicit error, because a tool that returns nothing did not do its job.
    """
    metadata: Dict[str, Any] = {}
    data: Any = None
    error_info: Optional[Dict[str, Any]] = None
    status = STATUS_OK
    output = ""

    if isinstance(raw, ToolCallResult):
        result = raw
        result.name = result.name or name
        result.tool_call_id = result.tool_call_id or tool_call_id
        result.started_at = result.started_at or started_at
        result.output, truncated = truncate_output(result.output or "", max_output_chars)
        result.stdout = result.output
        if truncated:
            result.metadata = {**(result.metadata or {}), "output_truncated": True}
        return finish_envelope(result, monotonic_start)

    if isinstance(raw, ToolResult):
        output = str(raw.output or "")
        error_text = str(raw.error or "")
        metadata = dict(raw.metadata or {})
        if raw.success:
            status = STATUS_OK
        else:
            status = STATUS_ERROR
            error_info = {
                "type": str(metadata.get("error_type") or "ToolError"),
                "message": error_text or "Tool reported failure without a message",
                "retryable": bool(metadata.get("retryable", False)),
            }
    elif raw is None:
        status = STATUS_ERROR
        error_info = {
            "type": "EmptyToolResult",
            "message": f"Tool '{name}' returned no result object",
            "retryable": False,
        }
    elif isinstance(raw, dict):
        data = raw
        metadata = dict(raw.get("metadata") or {})
        raw_status = str(raw.get("status") or "").lower()
        success = raw.get("success")
        error_text = raw.get("error")
        if raw_status in VALID_STATUSES:
            status = raw_status
        elif success is False or error_text:
            status = STATUS_ERROR
        else:
            status = STATUS_OK
        output = str(raw.get("output") or raw.get("stdout") or "")
        if not output:
            try:
                output = json.dumps(raw, default=str)[:max_output_chars]
            except Exception:  # noqa: BLE001
                output = str(raw)
        if status != STATUS_OK:
            if isinstance(error_text, dict):
                error_info = {
                    "type": str(error_text.get("type") or "ToolError"),
                    "message": str(error_text.get("message") or "Tool reported failure"),
                    "retryable": bool(error_text.get("retryable", False)),
                }
            else:
                error_info = {
                    "type": "ToolError",
                    "message": str(error_text or "Tool reported failure"),
                    "retryable": False,
                }
    elif isinstance(raw, str):
        output = raw
    else:
        data = raw
        output = str(raw)

    output, truncated = truncate_output(output, max_output_chars)
    if truncated:
        metadata["output_truncated"] = True

    result = ToolCallResult(
        success=status == STATUS_OK,
        output=output,
        error=(error_info or {}).get("message", "") if error_info else "",
        metadata=metadata,
        tool_call_id=tool_call_id,
        name=name,
        status=status,
        started_at=started_at,
        data=data,
        stdout=output,
        stderr=(error_info or {}).get("message", "") if error_info else "",
        error_info=error_info,
    )
    return finish_envelope(result, monotonic_start)


def error_result(
    exc: BaseException,
    *,
    name: str,
    tool_call_id: str,
    started_at: str,
    monotonic_start: float,
    status: str = STATUS_ERROR,
) -> ToolCallResult:
    info = classify_error(exc)
    if status == STATUS_TIMEOUT:
        info["retryable"] = True
    result = ToolCallResult(
        success=False,
        output="",
        error=info["message"],
        metadata={"error_type": info["type"]},
        tool_call_id=tool_call_id,
        name=name,
        status=status,
        started_at=started_at,
        stderr=info["message"],
        error_info=info,
    )
    return finish_envelope(result, monotonic_start)


# ──────────────────────────────────────────────────────────────────────
# Tool argument parsing / repair
# ──────────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*|\s*```\s*$")


class ToolArgumentError(ValueError):
    """Raised when tool-call arguments cannot be parsed even after repair."""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text)
    return text.strip()


def _repair_truncated_json(text: str) -> str:
    """Close unbalanced strings/brackets in a truncated JSON object."""
    in_string = False
    escaped = False
    stack: list = []
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    repaired = text
    if in_string:
        repaired += '"'
    # Drop a dangling ``"key":`` or trailing comma before closing.
    repaired = re.sub(r",\s*$", "", repaired)
    repaired = re.sub(r'(?:,\s*)?"[^"]*"\s*:\s*$', "", repaired)
    repaired = re.sub(r",\s*$", "", repaired)
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    return repaired


def parse_tool_arguments(raw: Any, *, tool_name: str = "") -> Dict[str, Any]:
    """Parse model-produced tool arguments into a dict, repairing when possible.

    Accepts: dict, None/empty, JSON string, fenced JSON, single-quoted
    pseudo-JSON, JSON with trailing commas, and truncated JSON.
    Raises :class:`ToolArgumentError` when nothing usable can be recovered.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        raise ToolArgumentError(
            f"Tool '{tool_name}' arguments must be a mapping or JSON string, got {type(raw).__name__}"
        )

    text = _strip_fences(raw)
    if not text or text in {"null", "None"}:
        return {}

    # 1. straight JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        raise ToolArgumentError(
            f"Tool '{tool_name}' arguments must decode to an object, got {type(parsed).__name__}"
        )
    except ToolArgumentError:
        raise
    except json.JSONDecodeError:
        pass

    # 2. slice out the outermost object
    start = text.find("{")
    if start > 0:
        text = text[start:]

    # 3. remove trailing commas
    candidate = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 4. python-literal (single quotes, True/False/None)
    try:
        parsed = ast.literal_eval(candidate)
        if isinstance(parsed, dict):
            return {str(k): v for k, v in parsed.items()}
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        pass

    # 5. repair truncation
    repaired = _repair_truncated_json(candidate)
    try:
        parsed = json.loads(repaired)
        if isinstance(parsed, dict):
            # A dangling value such as ``{"path":`` used to be repaired to
            # ``{}``, silently discarding the model's argument text.  That
            # turns a transport/protocol defect into a misleading missing
            # parameter error and makes the repair loop repeat the same call.
            # Only accept an empty repaired object when the original payload
            # was explicitly empty.
            if not parsed and candidate.strip() not in {"{}", "{ }"}:
                raise ToolArgumentError(
                    f"Tool '{tool_name}' arguments were truncated before a usable value"
                )
            return parsed
    except json.JSONDecodeError:
        pass

    raise ToolArgumentError(
        f"Tool '{tool_name}' arguments are not valid JSON: {raw[:200]!r}"
    )
