from __future__ import annotations

__version__ = "2.0.0"
import os
import asyncio
from glob import glob

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class ShortcutsTool(BaseTool):
    name = "shortcuts"
    description = "Quick utility helpers: list, pwd, tree, info, find"

    def is_read_only(self, params=None) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True

    async def execute(self, action: str = "list", path: str = "", pattern: str = "", **kwargs) -> ToolResult:
        """Run filesystem-heavy shortcut operations without blocking the loop."""
        return await asyncio.to_thread(
            self._execute_sync, action, path, pattern, **kwargs
        )

    def _execute_sync(self, action: str = "list", path: str = "", pattern: str = "", **kwargs) -> ToolResult:
        try:
            action = (action or "list").strip().lower()
            root = os.path.realpath(os.path.abspath(self.root_dir or os.getcwd()))
            raw = os.path.join(root, path) if path and not os.path.isabs(path) else (path or root)
            target = os.path.abspath(os.path.normpath(raw))
            # Workspace containment must follow symlinks, not only compare
            # lexical paths. Otherwise an in-workspace link can expose files
            # outside the workspace to list/tree/info/find operations.
            if not self._within_root(root, target):
                return ToolResult(success=False, error=f"Path traversal blocked: {path or '.'}")

            if action == "pwd":
                return ToolResult(success=True, output=os.path.abspath(root))

            if action == "list":
                if not os.path.isdir(target):
                    return ToolResult(success=False, error=f"Directory not found: {path or '.'}")
                entries = sorted(os.listdir(target))
                lines = [f"Contents of: {path or '.'}"]
                for e in entries:
                    full = os.path.join(target, e)
                    suffix = "/" if os.path.isdir(full) else ""
                    lines.append(f"  {e}{suffix}")
                return ToolResult(success=True, output="\n".join(lines))

            if action == "tree":
                if not os.path.isdir(target):
                    return ToolResult(success=False, error=f"Directory not found: {path or '.'}")
                lines = [f"Tree of: {path or '.'}"]
                self._build_tree(target, lines, "")
                return ToolResult(success=True, output="\n".join(lines))

            if action == "info":
                if not os.path.exists(target):
                    return ToolResult(success=False, error=f"Path not found: {path}")
                stat = os.stat(target)
                kind = "Directory" if os.path.isdir(target) else "File"
                size = stat.st_size if not os.path.isdir(target) else ""
                modified = stat.st_mtime
                import datetime
                mt = datetime.datetime.fromtimestamp(modified).isoformat()
                parts = [f"{kind}: {path}"]
                if size:
                    parts.append(f"Size: {size} bytes")
                parts.append(f"Modified: {mt}")
                return ToolResult(success=True, output="\n".join(parts))

            if action == "find":
                p = pattern or "*"
                matches = [
                    match
                    for match in glob(os.path.join(target, p), recursive=True)
                    if self._within_root(root, match)
                ][:100]
                if not matches:
                    return ToolResult(success=True, output=f"No matches for: {p}")
                lines = [f"Matches for: {p}"]
                for m in sorted(matches):
                    rel = os.path.relpath(m, root)
                    suffix = "/" if os.path.isdir(m) else ""
                    lines.append(f"  {rel}{suffix}")
                return ToolResult(success=True, output="\n".join(lines))

            return ToolResult(success=False, error=f"Unknown action: {action}. Use: list, pwd, tree, info, find")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    @staticmethod
    def _within_root(root: str, candidate: str) -> bool:
        """Return whether candidate resolves inside the workspace root."""
        try:
            return os.path.commonpath([root, os.path.realpath(candidate)]) == root
        except ValueError:
            return False

    @staticmethod
    def _build_tree(dirpath: str, lines: list, prefix: str):
        entries = sorted(os.listdir(dirpath))
        for i, e in enumerate(entries):
            if e.startswith("."):
                continue
            full = os.path.join(dirpath, e)
            is_last = i == len(entries) - 1
            connector = "+-- " if is_last else "|-- "
            is_link = os.path.islink(full)
            lines.append(
                f"{prefix}{connector}{e}{'@' if is_link else '/' if os.path.isdir(full) else ''}"
            )
            # Do not follow links during recursive tree traversal. The
            # requested root itself is validated separately, while child
            # links can create cycles or point outside the workspace.
            if os.path.isdir(full) and not is_link:
                ext = "    " if is_last else "|   "
                try:
                    ShortcutsTool._build_tree(full, lines, prefix + ext)
                except PermissionError:
                    lines.append(f"{prefix}{ext}[permission denied]")
