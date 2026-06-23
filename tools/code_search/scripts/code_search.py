from __future__ import annotations
__version__ = "1.0.0"
import re
import os
from pathlib import Path
from typing import Optional, List
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class CodeSearchTool(BaseTool):
    name = "code_search"
    description = "Search code with glob, regex, and structure analysis"

    async def execute(self, pattern: str, path: str = ".", include: Optional[str] = None, mode: str = "grep", **kwargs) -> ToolResult:
        try:
            root = Path(self.root_dir) if self.root_dir else Path.cwd()
            search_path = root / path

            if mode == "grep":
                results: List[str] = []
                for fpath in search_path.rglob("*"):
                    if fpath.is_file() and (not include or fpath.match(include)):
                        try:
                            for i, line in enumerate(fpath.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                                if re.search(pattern, line):
                                    rel = fpath.relative_to(root) if fpath.is_relative_to(root) else fpath
                                    results.append(f"{rel}:{i}: {line.strip()[:200]}")
                        except Exception:
                            pass
                return ToolResult(success=True, output="\n".join(results[:500]) or "No matches found")

            elif mode == "glob":
                matches = [str(p.relative_to(root)) if p.is_relative_to(root) else str(p) for p in search_path.rglob(pattern)]
                return ToolResult(success=True, output="\n".join(matches[:500]) or "No matches found")

            return ToolResult(success=False, error=f"Unknown mode: {mode}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
