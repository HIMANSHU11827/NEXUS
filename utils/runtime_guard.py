"""Runtime write-guard for NEXUS core source files.

NEXUS must never rewrite its own runtime modules while running. A live process
once corrupted ``orchestrators/loop.py`` at runtime (injected typo + duplicated
lines). This module provides a cheap, monkey-patch-free guard that evolution /
self-improvement call paths invoke before touching any file.

Usage:
    from utils.runtime_guard import assert_not_rewriting_core, protected_core_writes

    assert_not_rewriting_core(path)          # raises PermissionError if protected

    with protected_core_writes():            # scoped marker + violation logging
        ...evolution work...
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
    """
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
