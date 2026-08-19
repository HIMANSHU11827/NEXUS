"""Aider-style repo map — lightweight symbol index for planner context.

Inspired by Aider's tree-sitter + PageRank repo map: instead of dumping
entire files into context, extract class/function definitions and inject
a token-budgeted symbol overview so the planner knows WHAT exists and
WHERE it lives.

This is a lightweight implementation that uses regex-based extraction
(no tree-sitter dependency) for broad compatibility.  The output is a
compact text block injected into the system prompt or planner context
with a configurable token budget.

Benefits (from Aider benchmarks):
- Model sees the code structure, not raw file contents
- 5-8% better code generation accuracy with architect/editor split
- Token-efficient: ~1/8 of context window by default
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default: reserve ~8K chars (~2K tokens) for the repo map
_DEFAULT_MAX_CHARS = 8000
_DEFAULT_MAX_FILES = 200

# Regex patterns for Python symbol extraction
_PY_CLASS_RE = re.compile(r"^class\s+(\w+)", re.MULTILINE)
_PY_DEF_RE = re.compile(r"^(?:async\s+)?def\s+(\w+)", re.MULTILINE)
_PY_IMPORT_RE = re.compile(r"^(?:from\s+\S+\s+)?import\s+(\S+)", re.MULTILINE)

# Patterns for TypeScript/JavaScript
_TS_CLASS_RE = re.compile(r"(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)
_TS_FUNC_RE = re.compile(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE)
_TS_INTERFACE_RE = re.compile(r"(?:export\s+)?interface\s+(\w+)", re.MULTILINE)
_TS_TYPE_RE = re.compile(r"(?:export\s+)?type\s+(\w+)", re.MULTILINE)


def _extract_python_symbols(path: Path, content: str) -> Dict[str, Any]:
    """Extract class and function definitions from Python source."""
    classes = [m.group(1) for m in _PY_CLASS_RE.finditer(content)]
    functions = [m.group(1) for m in _PY_DEF_RE.finditer(content)]
    return {
        "classes": classes[:50],
        "functions": functions[:100],
        "lines": content.count("\n") + 1,
    }


def _extract_ts_symbols(path: Path, content: str) -> Dict[str, Any]:
    """Extract class, function, interface, type definitions from TS/JS."""
    classes = [m.group(1) for m in _TS_CLASS_RE.finditer(content)]
    functions = [m.group(1) for m in _TS_FUNC_RE.finditer(content)]
    interfaces = [m.group(1) for m in _TS_INTERFACE_RE.finditer(content)]
    types = [m.group(1) for m in _TS_TYPE_RE.finditer(content)]
    return {
        "classes": classes[:50],
        "functions": functions[:100],
        "interfaces": interfaces[:30],
        "types": types[:30],
        "lines": content.count("\n") + 1,
    }


def _extract_symbols(path: Path, content: str) -> Dict[str, Any]:
    """Extract symbols from a source file based on extension."""
    ext = path.suffix.lower()
    if ext == ".py":
        return _extract_python_symbols(path, content)
    if ext in (".ts", ".tsx", ".js", ".jsx"):
        return _extract_ts_symbols(path, content)
    # Generic: just count lines
    return {"lines": content.count("\n") + 1}


def _relative_path(path: Path, root: Path) -> str:
    """Get a clean relative path."""
    try:
        return str(path.relative_to(root)).replace(os.sep, "/")
    except ValueError:
        return str(path)


def build_repo_map(
    root_dir: str,
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
    max_files: int = _DEFAULT_MAX_FILES,
    include_patterns: Optional[List[str]] = None,
    exclude_dirs: Optional[List[str]] = None,
) -> str:
    """Build a compact symbol-level overview of the repository.

    Args:
        root_dir: Repository root directory.
        max_chars: Maximum characters for the output map.
        max_files: Maximum number of files to index.
        include_patterns: File extensions to include (default: .py, .ts, .js).
        exclude_dirs: Directories to skip (default: node_modules, .venv, __pycache__).

    Returns:
        Compact text map of ``file: class1, func1, func2 ...`` lines.
    """
    root = Path(root_dir).resolve()
    if not root.is_dir():
        return ""

    include = set(include_patterns or [".py", ".ts", ".tsx", ".js", ".jsx"])
    excludes = set(exclude_dirs or {
        "node_modules", ".venv", "__pycache__", ".git", ".nexus",
        "dist", "build", ".next", "coverage", ".ruff_cache",
    })

    entries: List[Tuple[str, Dict[str, Any]]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in include:
            continue
        # Skip excluded directories
        parts = path.relative_to(root).parts
        if any(part in excludes for part in parts):
            continue
        if len(entries) >= max_files:
            break

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            symbols = _extract_symbols(path, content)
            rel = _relative_path(path, root)
            entries.append((rel, symbols))
        except Exception:
            continue

    # Build the map text
    lines: List[str] = []
    total_chars = 0

    for rel_path, symbols in entries:
        parts: List[str] = []

        classes = symbols.get("classes", [])
        if classes:
            parts.append(f"class {', '.join(classes[:10])}")

        functions = symbols.get("functions", [])
        if functions:
            # Show first 8 functions; note total if more
            shown = functions[:8]
            suffix = f" (+{len(functions) - 8} more)" if len(functions) > 8 else ""
            parts.append(f"def {', '.join(shown)}{suffix}")

        interfaces = symbols.get("interfaces", [])
        if interfaces:
            parts.append(f"interface {', '.join(interfaces[:8])}")

        types = symbols.get("types", [])
        if types:
            parts.append(f"type {', '.join(types[:8])}")

        lines_count = symbols.get("lines", 0)
        if not parts:
            # No extractable symbols — still useful to show the file exists
            parts.append(f"({lines_count} lines)")

        line = f"{rel}: {'; '.join(parts)}"
        if total_chars + len(line) + 1 > max_chars:
            break
        lines.append(line)
        total_chars += len(line) + 1

    return "\n".join(lines)


async def build_repo_map_async(
    root_dir: str,
    **kwargs: Any,
) -> str:
    """Non-blocking wrapper around build_repo_map."""
    import asyncio
    return await asyncio.to_thread(build_repo_map, root_dir, **kwargs)


def inject_repo_map(system_prompt: str, repo_map: str, *, max_chars: int = 8000) -> str:
    """Inject a repo map block into a system prompt.

    Appends a ``=== REPOSITORY MAP ===`` section to the prompt so the model
    has symbol-level awareness of the codebase.
    """
    if not repo_map or not repo_map.strip():
        return system_prompt

    trimmed = repo_map[:max_chars]
    if len(repo_map) > max_chars:
        trimmed += "\n...[truncated]"

    return f"{system_prompt}\n\n=== REPOSITORY MAP ===\n{trimmed}"
