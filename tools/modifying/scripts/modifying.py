from __future__ import annotations

__version__ = "2.0.0"
import asyncio
import os

from tools.nexus_tools.base_tool import BaseTool, ToolResult


def _normalize_quotes(text: str) -> str:
    """Collapse typographic (curly) quotes to straight ASCII quotes.

    Length-preserving (1 char → 1 char) so offset math stays valid when the
    match positions are applied back onto the original file content.
    """
    return (
        str(text)
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )


def _find_occurrences(content: str, needle: str) -> list:
    """Return all (non-overlapping) start offsets of ``needle`` in ``content``."""
    positions = []
    start = 0
    while True:
        idx = content.find(needle, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + len(needle)
    return positions


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "on", "1"}


class ModifyingTool(BaseTool):
    name = "modifying"
    description = "Edit text in an existing file"

    async def execute(self, path: str, old_string: str, new_string: str = "", replace_all: bool = False, **kwargs) -> ToolResult:
        """Edit a file without blocking the event loop on file I/O."""
        return await asyncio.to_thread(
            self._execute_sync, path, old_string, new_string, replace_all, **kwargs
        )

    def _execute_sync(self, path: str, old_string: str, new_string: str = "", replace_all: bool = False, **kwargs) -> ToolResult:
        try:
            full = os.path.normpath(os.path.join(self.root_dir, path)) if self.root_dir and not os.path.isabs(path) else os.path.normpath(path)
            if self.root_dir and os.path.commonpath([os.path.abspath(self.root_dir), full]) != os.path.abspath(self.root_dir):
                return ToolResult(success=False, error=f"Path traversal blocked: {path}")
            if not os.path.isfile(full):
                return ToolResult(success=False, error=f"File not found: {path}")
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            # Normalize curly quotes on both sides so a straight-quote
            # old_string matches typographic quotes, without rewriting the file.
            needle = _normalize_quotes(old_string)
            norm_content = _normalize_quotes(content)
            positions = _find_occurrences(norm_content, needle)
            if not positions:
                return ToolResult(success=False, error=f"old_string not found in: {path}")
            if len(positions) > 1 and not _as_bool(replace_all):
                return ToolResult(
                    success=False,
                    error=(
                        f"Found {len(positions)} matches of the old_string; "
                        "provide more surrounding context or set replace_all: true"
                    ),
                )
            targets = positions if _as_bool(replace_all) else positions[:1]
            new_content = content
            old_len = len(old_string)
            # Replace from the end so earlier offsets stay valid.
            for idx in reversed(targets):
                new_content = new_content[:idx] + new_string + new_content[idx + old_len:]
            with open(full, "w", encoding="utf-8") as f:
                f.write(new_content)
            return ToolResult(
                success=True,
                output=f"Modified: {path}",
                metadata={"path": full, "replacements": len(targets), "bytes": len(new_content)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
