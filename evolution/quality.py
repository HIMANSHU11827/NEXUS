"""Shared quality gates for the evolution forges.

Two responsibilities live here, both used by every forge under
``evolution/*_forge/``:

1. ``validate_forge_output(kind, output, root, write_path)`` — the promotion
   gate. A forge result is only marked ``promoted`` when its on-disk payload
   passes structural validation: non-empty, all required fields for that forge
   kind, no PII/secret-like tokens, and a write path inside the allowed dir for
   that kind. A failed validation marks the result ``rejected`` and the forge
   refuses to write it (recording the rejection in the ledger instead).

2. ``forge_guard(kind)`` — fault-isolating decorator for every forge public
   call. A failing forge never raises into the runtime; it returns a structured
   ``{status: "failed", reason, evidence: {stdout, stderr}}`` and the captured
   stdout/stderr is preserved as evidence instead of bubbling.
"""

from __future__ import annotations

__version__ = "1.0.0"

import contextlib
import functools
import io
import json
import logging
import os
import re
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Forge kind registry ───────────────────────────────────────────────────

FORGE_KINDS = ("tool", "skill", "plugin", "memory", "knowledge")

# Every forge kind maps to the (relative) directory that is allowed to receive
# its writes. Anything outside these bases is rejected as an unsafe write path.
FORGE_ALLOWED_DIRS: Dict[str, tuple] = {
    "tool": ("tools",),
    "skill": ("skills",),
    "plugin": ("plugins",),
    "memory": ("data", "memory_forge"),
    "knowledge": ("knowledge", "library"),
}

# Structural minimum an artifact payload must satisfy before promotion.
FORGE_REQUIRED_FIELDS: Dict[str, tuple] = {
    "tool": ("name", "version", "description", "defaults", "permissions"),
    "skill": ("name", "version"),
    "plugin": ("name", "version", "description"),
    "memory": ("title", "content", "version"),
    "knowledge": ("title", "content", "version"),
}

# ── PII / secret-like token scan ──────────────────────────────────────────

_SECRET_PATTERNS = (
    # OpenAI / Anthropic / Cohere / Mistral style "sk-...", "pk-...", "rk-..."
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b"),
    # Gemini AIza...
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),
    # AWS access key
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # GitHub tokens
    re.compile(r"\b(?:ghp|gho|ghu|github_pat)_[A-Za-z0-9_]{20,}\b"),
    # Bearer auth tokens
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b", re.IGNORECASE),
    # PEM private keys
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # key=value credential assignments (api_key=..., password=..., secret=...)
    re.compile(
        r"\b(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token|password|passwd|secret|client[_-]?secret)\b"
        r"\s*[:=]\s*['\"]?[A-Za-z0-9_/+\-=\.]{8,}",
        re.IGNORECASE,
    ),
    # Long opaque hex/base64 blobs that are almost always keys or secrets.
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)


def looks_like_secret(text: str) -> bool:
    """True when ``text`` contains a PII/secret-like token (API key, password...)."""
    if not text:
        return False
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _stringify(value: Any) -> str:
    """Flatten arbitrary payload values into one searchable string."""
    try:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


# ── Provider-error / empty-evidence honesty guard (V5) ────────────────────

# Strong markers that indicate provider/API failure output that should never be
# crystallized as a Learning. Mirrors orchestrators' own failure markers but
# tightened so normal prose ("the router prefers X") is not rejected. Each
# marker is anchored with word boundaries so plain words ("error handling",
# "failure modes") in genuine learnings are not misread as failure evidence.
_PROVIDER_ERROR_MARKERS = (
    "traceback",
    "exception",
    "error",
    "failed",
    "failure",
    "not found",
    "exit code",
    "non-zero",
    "rate limit",
    "timed out",
    "timeout",
    "connection refused",
    "connection reset",
    "server error",
    "internal server error",
    "unauthorized",
    "authentication",
    "api error",
    "provider error",
    "token limit",
    "context length",
    "quota",
    "overloaded",
    "status code",
    "http error",
    "http 4",
    "http 5",
    "retrying",
)
_PROVIDER_ERROR_RE = tuple(
    re.compile(r"\b" + re.escape(marker) + r"\b", re.IGNORECASE)
    for marker in _PROVIDER_ERROR_MARKERS
)


def looks_like_provider_error(text: Optional[str]) -> bool:
    """True when the supplied evidence is empty/whitespace or error-shaped.

    Used by ``memory_forge``/``tool_forge`` so an LLM/provider error message
    (or empty evidence) is never crystallized as a ``Learning``.
    """
    content = str(text or "").strip()
    if not content:
        return True
    return any(pattern.search(content) for pattern in _PROVIDER_ERROR_RE)


# ── Path safety ────────────────────────────────────────────────────────────

def _path_inside(parent: str, target: str) -> bool:
    """True when ``target`` resolves strictly inside ``parent``."""
    try:
        parent_real = os.path.realpath(os.path.abspath(parent))
        target_real = os.path.realpath(os.path.abspath(target))
        if target_real == parent_real:
            return True
        return os.path.commonpath([parent_real, target_real]) == parent_real
    except Exception:
        return False


def allowed_write_path(path: str, kind: str, root: Optional[str] = None) -> bool:
    """True when ``path`` sits inside the allowed dir for ``kind`` under ``root``."""
    if not path:
        return False
    if not root:
        # No root provided: nothing to compare against — refuse conservatively.
        return False
    allowed = FORGE_ALLOWED_DIRS.get(kind)
    if allowed is None:
        return False
    base = os.path.abspath(os.path.join(os.path.abspath(root), *allowed))
    if not _path_inside(os.path.abspath(root), path):
        return False
    return _path_inside(base, path)


# ── Promotion gate ─────────────────────────────────────────────────────────

def validate_forge_output(kind: str, output: Any, root: Optional[str] = None,
                          write_path: Optional[str] = None) -> Dict[str, Any]:
    """Structural validation gate for a forge artifact payload.

    Returns ``{"valid": True, "status": "ok", ...}`` when the payload can be
    safely promoted, or ``{"valid": False, "status": "rejected", ...}`` with a
    human-readable ``reason`` otherwise. The forge must NOT write when invalid.
    """
    kind = (kind or "memory").lower()
    if kind not in FORGE_KINDS:
        return {
            "kind": kind, "valid": False, "status": "rejected",
            "errors": [f"unknown forge kind: {kind}"],
            "reason": f"unknown forge kind: {kind}",
        }

    errors: list = []

    if not isinstance(output, dict):
        errors.append("output is not a dict")
    elif not output:
        errors.append("output is empty")
    else:
        for field in FORGE_REQUIRED_FIELDS.get(kind, ("version",)):
            value = output.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"missing required field: {field}")

    if isinstance(output, dict) and output:
        if looks_like_secret(_stringify(output)):
            errors.append("output contains secret-like tokens (API key / password / token)")

    if write_path and not allowed_write_path(write_path, kind, root):
        errors.append(
            "write path outside allowed dir for kind '%s': %s" % (kind, write_path)
        )

    valid = not errors
    return {
        "kind": kind,
        "valid": valid,
        "status": "ok" if valid else "rejected",
        "reason": "; ".join(errors) if errors else "ok",
        "errors": errors,
    }


def rejected_result(kind: str, name: str, reason: str,
                    action: str = "forge") -> Dict[str, Any]:
    """Structured, non-promoted result shared by every forge on rejection."""
    return {
        "created": False,
        "status": "rejected",
        "promoted": False,
        "kind": kind,
        "name": name,
        "action": action,
        "reason": reason,
    }


# ── Fault isolation decorator ──────────────────────────────────────────────

_GUARD_LOCK = threading.RLock()


def forge_guard(kind: str):
    """Wrap a forge public method so it never raises into the runtime.

    Returns a structured ``{status: "failed", created: False, reason, evidence}
    `` where ``evidence`` preserves the captured stdout/stderr from the failed
    attempt. Success results are annotated with ``status``/``promoted`` without
    changing their existing keys, so callers (V5Evolution, omni kernel, tests)
    keep working unchanged.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            try:
                # Redirect under a lock: forges can run inside asyncio.to_thread
                # and swapping sys.stdout without synchronization would corrupt
                # other threads' output.
                with _GUARD_LOCK:
                    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                        result = fn(self, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - fault isolation boundary
                logger.warning("evolution/quality.py forge_guard: %s.%s failed: %s",
                               type(self).__name__, fn.__name__, exc)
                return {
                    "status": "failed",
                    "kind": kind,
                    "created": False,
                    "promoted": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "error": str(exc),
                    "evidence": {
                        "stdout": stdout_buf.getvalue().strip(),
                        "stderr": stderr_buf.getvalue().strip(),
                    },
                }
            if isinstance(result, dict):
                created = bool(result.get("created"))
                result.setdefault("status", "ok" if created else "rejected")
                result.setdefault("promoted", created)
                if "evidence" not in result:
                    result["evidence"] = {
                        "stdout": stdout_buf.getvalue().strip(),
                        "stderr": stderr_buf.getvalue().strip(),
                    }
            return result
        return wrapper
    return decorator


__all__ = [
    "FORGE_KINDS",
    "FORGE_ALLOWED_DIRS",
    "FORGE_REQUIRED_FIELDS",
    "looks_like_secret",
    "looks_like_provider_error",
    "allowed_write_path",
    "validate_forge_output",
    "rejected_result",
    "forge_guard",
]
