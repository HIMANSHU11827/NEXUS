from __future__ import annotations

__version__ = "2.0.0"
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("nexus.tools.code_search")

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class CodeSearchTool(BaseTool):
    name = "code_search"
    description = "Search code with glob, regex, and structure analysis"

    async def execute(self, pattern: str, path: str = ".", include: Optional[str] = None, mode: str = "grep", **kwargs) -> ToolResult:
        try:
            root = Path(self.root_dir).resolve() if self.root_dir else Path.cwd().resolve()
            search_path = (root / path).resolve()

            # Workspace containment: never scan directories outside the root.
            try:
                outside = os.path.commonpath([str(root), str(search_path)]) != str(root)
            except ValueError:
                outside = True
            if outside:
                return ToolResult(success=False, error=f"Path is outside the workspace: {path}")

            if mode == "grep":
                results: List[str] = []
                skipped: List[str] = []
                scanned_bytes = 0
                max_file_bytes = 8 * 1024 * 1024
                max_scan_bytes = 256 * 1024 * 1024
                ignored = {".git", ".venv", "node_modules", "__pycache__", ".cache", ".pytest_cache"}
                for current, dirs, files in os.walk(search_path):
                    dirs[:] = [d for d in dirs if d not in ignored]
                    for filename in files:
                        fpath = Path(current) / filename
                        if include and not fpath.match(include):
                            continue
                        try:
                            size = fpath.stat().st_size
                            if size > max_file_bytes or scanned_bytes + size > max_scan_bytes:
                                skipped.append(str(fpath))
                                continue
                            scanned_bytes += size
                            with fpath.open("r", encoding="utf-8", errors="replace") as handle:
                                for i, line in enumerate(handle, 1):
                                    if re.search(pattern, line):
                                        rel = fpath.relative_to(root) if fpath.is_relative_to(root) else fpath
                                        results.append(f"{rel}:{i}: {line.strip()[:200]}")
                                        if len(results) >= 500:
                                            break
                        except (OSError, UnicodeError) as exc:
                            skipped.append(f"{fpath}: {exc}")
                        if len(results) >= 500:
                            break
                    if len(results) >= 500:
                        break
                output = "\n".join(results[:500]) or "No matches found"
                if skipped:
                    output += f"\n[Skipped {len(skipped)} oversized/unreadable files]"
                return ToolResult(success=True, output=output, metadata={"scanned_bytes": scanned_bytes, "skipped": len(skipped)})

            elif mode == "glob":
                matches = [str(p.relative_to(root)) if p.is_relative_to(root) else str(p) for p in search_path.rglob(pattern)]
                return ToolResult(success=True, output="\n".join(matches[:500]) or "No matches found")

            return ToolResult(success=False, error=f"Unknown mode: {mode}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
