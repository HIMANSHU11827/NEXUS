from __future__ import annotations

__version__ = "1.0.0"
import os
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
        try:
            action = (action or "list").strip().lower()
            root = self.root_dir or os.getcwd()
            target = os.path.join(root, path) if path and not os.path.isabs(path) else (path or root)
            if not os.path.isabs(target) and not os.path.exists(target):
                target = os.path.join(root, target)

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
                matches = glob(os.path.join(target, p), recursive=True)[:100]
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
    def _build_tree(dirpath: str, lines: list, prefix: str):
        entries = sorted(os.listdir(dirpath))
        for i, e in enumerate(entries):
            if e.startswith("."):
                continue
            full = os.path.join(dirpath, e)
            is_last = i == len(entries) - 1
            connector = "+-- " if is_last else "|-- "
            lines.append(f"{prefix}{connector}{e}{'/' if os.path.isdir(full) else ''}")
            if os.path.isdir(full):
                ext = "    " if is_last else "|   "
                try:
                    ShortcutsTool._build_tree(full, lines, prefix + ext)
                except PermissionError:
                    lines.append(f"{prefix}{ext}[permission denied]")
