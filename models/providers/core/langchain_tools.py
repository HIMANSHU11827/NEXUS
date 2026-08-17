"""LangChain-compatible tools bound to the real NEXUS file/terminal/RAG backends.

No fake results: file writes and shell execution go through the project
sandbox/terminal tooling, and knowledge search uses the canonical RAG engine.
When a backend cannot be reached the tools return a truthful error string.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("nexus.langchain_tools")

# The LangChain decorator is optional: when langchain_core is not installed the
# tools still work as plain callables instead of failing at import time.
try:
    from langchain_core.tools import tool
except Exception:
    def tool(func=None, **kwargs):
        if func is None:
            return lambda fn: fn
        return func


try:
    from utils.nexus_path import _ROOT as _REPO_ROOT
except Exception:  # pragma: no cover - defensive
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WORKSPACE_ROOT = os.path.abspath(os.path.join(_REPO_ROOT, "workspace"))
KNOWLEDGE_VAULT = os.path.abspath(os.path.join(_REPO_ROOT, "knowledge"))


# --------------------------------------------------------------------------- files


def _resolve_workspace_path(name: str) -> str:
    """Resolve a workspace-relative path, rejecting escapes outside the root."""
    raw = str(name or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        raise ValueError(f"invalid workspace path: {name!r}")
    root_abs = os.path.abspath(WORKSPACE_ROOT)
    target = os.path.abspath(os.path.join(WORKSPACE_ROOT, raw))
    if target != root_abs and not target.startswith(root_abs + os.sep):
        raise ValueError(f"path escapes workspace: {name!r}")
    return target


def _write_file(name: str, content: str) -> str:
    """Write content to a file inside the workspace; returns a truthful report."""
    os.makedirs(WORKSPACE_ROOT, exist_ok=True)
    target = _resolve_workspace_path(name)
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    text = str(content)
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    rel = os.path.relpath(target, WORKSPACE_ROOT).replace("\\", "/")
    return f"Wrote {len(text)} bytes to workspace/{rel}"


def _read_file(name: str) -> str:
    """Read a file from the workspace; raises FileNotFoundError when missing."""
    target = _resolve_workspace_path(name)
    if not os.path.isfile(target):
        raise FileNotFoundError(f"no such file in workspace: {name!r}")
    with open(target, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


# --------------------------------------------------------------------------- terminal


def _run_command(command: str) -> str:
    """Execute a command through the project terminal tool (sandbox-backed).

    Prefers the async TerminalTool; falls back to the same SovereignSandbox
    engine synchronously.  Sandbox blocks and unavailable backends are
    reported truthfully, never faked.
    """
    cmd = str(command or "").strip()
    if not cmd:
        raise ValueError("empty command")
    try:
        from tools.terminal.scripts.terminal import TerminalTool

        result = asyncio.run(TerminalTool(WORKSPACE_ROOT).execute(cmd))
        if result is None:
            return "[TERMINAL_ERROR]: terminal tool returned no result"
        if getattr(result, "success", False):
            return str(getattr(result, "output", "") or "")
        error = getattr(result, "error", None) or getattr(result, "output", "") or "unknown error"
        return f"[TERMINAL_ERROR]: {error}"
    except Exception as exc:
        try:
            from sandbox.sandbox_manager import SovereignSandbox

            output = SovereignSandbox(WORKSPACE_ROOT).execute(cmd)
            blocked = any(marker in output for marker in (
                "[SANDBOX_BLOCK]", "[SANDBOX_TIMEOUT]", "[EXECUTION_ERROR]", "[SANDBOX_ERROR]",
            ))
            if blocked:
                return f"[SANDBOX_BLOCKED]: {output}"
            return output
        except Exception as exc2:
            return f"[TERMINAL_UNAVAILABLE]: {exc}; {exc2}"


# --------------------------------------------------------------------------- knowledge

_rag = None


def _get_rag():
    """Lazily build the canonical RAG engine over the knowledge vault."""
    global _rag
    if _rag is None:
        from rag.engine import NexusAtlasRAG

        _rag = NexusAtlasRAG(KNOWLEDGE_VAULT)
    return _rag


# --------------------------------------------------------------------------- tools


@tool
def run_shell(command: str) -> str:
    """Execute a shell command on the host system and return its output."""
    try:
        return _run_command(command)
    except Exception as exc:
        return f"[TERMINAL_ERROR]: {exc}"


@tool
def write_file(filename_and_content: str) -> str:
    """
    Write content to a file in the workspace.
    Input format: 'filename.ext|||file content here'
    """
    try:
        name, content = filename_and_content.split("|||", 1)
        return _write_file(name.strip(), content.strip())
    except Exception as exc:
        return f"Error: {exc}"


@tool
def read_file(filename: str) -> str:
    """Read and return the content of a file from the workspace."""
    try:
        return _read_file(filename.strip())
    except Exception as exc:
        return f"Error: {exc}"


@tool
def knowledge_search(query: str) -> str:
    """Search the NEXUS knowledge vault for relevant stored information."""
    try:
        return _get_rag().retrieve_as_text(str(query or ""))
    except Exception as exc:
        return f"Error: knowledge search unavailable: {exc}"


@tool
def knowledge_store(key_and_content: str) -> str:
    """
    Store a fact into the NEXUS knowledge vault.
    Input format: 'key|||content'
    """
    try:
        key, content = key_and_content.split("|||", 1)
        _get_rag().store_document(key.strip(), content.strip())
        return f"Stored '{key.strip()}' in knowledge vault."
    except Exception as exc:
        return f"Error: {exc}"


# Export as a list for easy import
NEXUS_TOOLS = [run_shell, write_file, read_file, knowledge_search, knowledge_store]

__all__ = ["NEXUS_TOOLS", "run_shell", "write_file", "read_file", "knowledge_search", "knowledge_store"]
