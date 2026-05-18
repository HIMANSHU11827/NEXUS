"""
NEXUS GLOB TOOL — Claude Code GlobTool adapted for Python.
Fast file pattern matching with glob patterns.
"""

import os
import glob as glob_mod
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class GlobTool(BaseTool):
    name = "glob"
    description = "Find files matching glob patterns (e.g., '**/*.py', 'src/**/*.ts')"
    aliases = ["find_files", "ls_pattern"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, pattern: str = "**/*", path: str = None, **kwargs) -> ToolResult:
        search_path = os.path.abspath(path) if path else self.root
        full_pattern = os.path.join(search_path, pattern)
        matches = glob_mod.glob(full_pattern, recursive=True)
        matches = [os.path.relpath(m, self.root) for m in matches[:100]]
        if not matches:
            return ToolResult(data="No files found matching pattern.")
        return ToolResult(data="\n".join(matches))

    def is_read_only(self, input_data=None):
        return True
