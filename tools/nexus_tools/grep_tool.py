"""
NEXUS GREP TOOL — Claude Code GrepTool adapted for Python.
Regex-based content search across files.
"""

import os
import re
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class GrepTool(BaseTool):
    name = "grep"
    description = "Search file contents using regex patterns."
    aliases = ["search", "find_content"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(
        self, pattern: str = "", path: str = ".", include: str = None, **kwargs
    ) -> ToolResult:
        if not pattern:
            return ToolResult(error="No search pattern provided")

        search_path = os.path.join(self.root, path) if not os.path.isabs(path) else path
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return ToolResult(error=f"Invalid regex: {e}")

        results = []
        exclude_dirs = {".git", "__pycache__", "node_modules", "venv"}

        for root, dirs, files in os.walk(search_path):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for f in files:
                if include and not f.endswith(include.replace("*", "")):
                    continue
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                        for i, line in enumerate(fh, 1):
                            if regex.search(line):
                                rel = os.path.relpath(fpath, self.root)
                                results.append(f"{rel}:{i}: {line.rstrip()}")
                                if len(results) >= 50:
                                    break
                except (OSError, IOError):
                    continue
                if len(results) >= 50:
                    break

        return ToolResult(data="\n".join(results) if results else "No matches found.")

    def is_read_only(self, input_data=None):
        return True
