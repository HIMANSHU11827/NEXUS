"""Runtime write-guard for NEXUS core source files.

NEXUS must never rewrite its own runtime modules while running. A live process
once corrupted ``orchestrators/loop.py`` at runtime (injected typo + duplicated
lines). This module provides a cheap, monkey-patch-free guard that evolution /
self-improvement call paths invoke before touching any file.

Usage:
    from utils.runtime_guard import (
        assert_not_rewriting_core,
        guarded_write_text,
        guarded_append_text,
        guarded_jsonl_append,
        protected_core_writes,
    )

    assert_not_rewriting_core(path)          # raises PermissionError if protected

    guarded_write_text(path, "...")           # write, blocks core paths
    guarded_append_text(path, "...")          # append, blocks core paths
    guarded_jsonl_append(path, record)        # append JSONL line, blocks core paths

    with protected_core_writes():             # scoped marker + violation logging
        ...evolution work...

The guard is active by default. Set ``NEXUS_DISABLE_RUNTIME_GUARD=1`` (or call
``set_enabled(False)``) to bypass it for legitimate maintenance.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterable, Union

logger = logging.getLogger("nexus.runtime_guard")

# Top-level package directories that make up the running core of NEXUS.
PROTECTED_DIRS = ("orchestrators", "kernel", "nexus", "server")

# Repo root = parent of utils/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PathLike = Union[str, "os.PathLike[str]"]

# Master kill-switch so legitimate maintenance / test harnesses can disable the
# guard. It is ON by default; set NEXUS_DISABLE_RUNTIME_GUARD=1/true/yes/on to
# bypass it. The guard is deliberately opt-out, not opt-in.
_ENABLED = os.environ.get("NEXUS_DISABLE_RUNTIME_GUARD", "").lower() not in (
    "1",
    "true",
    "yes",
    "on",
)


def set_enabled(value: bool) -> bool:
    """Enable/disable the guard globally. Returns the previous state.

    Useful for tests and for legitimate one-off maintenance that must touch a
    protected module with the operator's explicit consent.
    """
    global _ENABLED
    previous = _ENABLED
    _ENABLED = bool(value)
    logger.info("[RUNTIME_GUARD] enabled=%s (was %s)", _ENABLED, previous)
    return previous


def is_enabled() -> bool:
    """Current global enable state of the guard."""
    return _ENABLED


class CoreRewriteBlocked(PermissionError):
    """Raised when a runtime component tries to write to a core source file."""


def _normalize(path: PathLike) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_core_path(path: PathLike, protected: Iterable[str] = PROTECTED_DIRS) -> bool:
    """True if *path* lives under one of the protected core package dirs."""
    try:
        target = _normalize(path)
    except Exception:
        return False
    root = _normalize(PROJECT_ROOT)
    for name in protected:
        base = os.path.join(root, os.path.normcase(name))
        if target == base or target.startswith(base + os.sep):
            return True
    return False


def assert_not_rewriting_core(path: PathLike, operation: str = "write") -> str:
    """Abort the caller if *path* targets a protected core source file.

    Returns the fspath unchanged when the write is allowed so callers can do::

        with open(assert_not_rewriting_core(p), "w") as f: ...

    Honors the global enable flag (see :func:`set_enabled`); when disabled this
    is a no-op pass-through so legitimate maintenance can be performed.
    """
    if not _ENABLED:
        return os.fspath(path)
    p = os.fspath(path)
    if is_core_path(p):
        msg = (
            f"[RUNTIME_GUARD] BLOCKED {operation} to protected core path: {p} "
            f"(protected dirs: {', '.join(PROTECTED_DIRS)})"
        )
        logger.error(msg)
        raise CoreRewriteBlocked(msg)
    return p


def guarded_open(path: PathLike, mode: str = "r", *args, **kwargs):
    """``open()`` wrapper that blocks mutating modes on core source files."""
    if any(ch in mode for ch in ("w", "a", "x", "+")):
        assert_not_rewriting_core(path, operation=f"open(mode={mode!r})")
    return open(path, mode, *args, **kwargs)


def guarded_unlink(path: PathLike) -> None:
    """``os.unlink`` wrapper that blocks deletion of core source files."""
    assert_not_rewriting_core(path, operation="unlink")
    os.unlink(path)


def guarded_write_text(
    path: PathLike, content: str, *, encoding: str = "utf-8", errors=None
) -> int:
    """Write *content* to *path* (create parent dirs), blocking core paths.

    Returns the number of characters written. Raises :class:`CoreRewriteBlocked`
    if *path* resolves under a protected core directory.
    """
    p = assert_not_rewriting_core(path, operation="write_text")
    parent = os.path.dirname(os.path.abspath(p))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(p, "w", encoding=encoding, errors=errors) as f:
        return f.write(content)


def guarded_append_text(
    path: PathLike, content: str, *, encoding: str = "utf-8", errors=None
) -> int:
    """Append *content* to *path* (create parent dirs), blocking core paths.

    Returns the number of characters appended. Raises :class:`CoreRewriteBlocked`
    if *path* resolves under a protected core directory. This is the helper
    evolution / self-improvement loggers should use for their JSONL appenders.
    """
    p = assert_not_rewriting_core(path, operation="append_text")
    parent = os.path.dirname(os.path.abspath(p))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(p, "a", encoding=encoding, errors=errors) as f:
        return f.write(content)


def guarded_jsonl_append(path: PathLike, record) -> int:
    """Serialize *record* (dict/dataclass/JSON-serializable) and append as one
    JSONL line to *path*, blocking core paths.

    Returns the number of characters written. Raises :class:`CoreRewriteBlocked`
    if *path* resolves under a protected core directory.
    """
    import json as _json

    try:
        text = _json.dumps(record, ensure_ascii=False)
    except TypeError:
        # Fall back to dataclass / object field extraction.
        try:
            from dataclasses import asdict

            text = _json.dumps(asdict(record), ensure_ascii=False)
        except Exception:
            text = _json.dumps(str(record), ensure_ascii=False)
    return guarded_append_text(path, text + "\n")


@contextmanager
def protected_core_writes(context: str = "evolution"):
    """Scope marker for self-improvement / evolution work.

    Any :class:`CoreRewriteBlocked` raised inside is logged with the context and
    re-raised so the offending write aborts (but the feature itself keeps
    running — callers already suppress per-step errors).
    """
    logger.debug("[RUNTIME_GUARD] protected scope enter: %s", context)
    try:
        yield
    except CoreRewriteBlocked as exc:
        logger.error("[RUNTIME_GUARD] violation in %s: %s", context, exc)
        raise
    finally:
        logger.debug("[RUNTIME_GUARD] protected scope exit: %s", context)


def verify_core_integrity(root: str | None = None) -> bool:
    """Startup check: orchestrators/loop.py parses and has no corruption marker."""
    import ast

    root = root or PROJECT_ROOT
    loop_path = os.path.join(root, "orchestrators", "loop.py")
    if not os.path.isfile(loop_path):
        logger.warning("[RUNTIME_GUARD] loop.py not found at %s", loop_path)
        return False
    try:
        src = open(loop_path, "r", encoding="utf-8", errors="replace").read()
    except Exception as exc:
        logger.error("[RUNTIME_GUARD] cannot read loop.py: %s", exc)
        return False
    if "getcworkspace" in src:
        logger.error(
            "[RUNTIME_GUARD] CORRUPTION DETECTED in orchestrators/loop.py: "
            "'getcworkspace' marker present — core file was rewritten at runtime."
        )
        return False
    try:
        ast.parse(src)
    except SyntaxError as exc:
        logger.error("[RUNTIME_GUARD] orchestrators/loop.py fails to parse: %s", exc)
        return False
    return True
