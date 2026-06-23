from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class FileOpsTool(BaseTool):
    name = "file_ops"
    description = "Read, write, edit, and manage files"

    async def execute(self, action: str, path: str, content: Optional[str] = None, old_string: Optional[str] = None, new_string: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            root = Path(self.root_dir) if self.root_dir else Path.cwd()
            target = root / path if not os.path.isabs(path) else Path(path)

            if action == "read":
                if not target.exists():
                    return ToolResult(success=False, error=f"File not found: {path}")
                text = target.read_text(encoding="utf-8")
                return ToolResult(success=True, output=text)

            elif action == "write":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content or "", encoding="utf-8")
                return ToolResult(success=True, output=f"Written {len(content or '')} bytes to {path}")

            elif action == "edit":
                if not target.exists():
                    return ToolResult(success=False, error=f"File not found: {path}")
                text = target.read_text(encoding="utf-8")
                if old_string and old_string in text:
                    text = text.replace(old_string, new_string or "", 1)
                    target.write_text(text, encoding="utf-8")
                    return ToolResult(success=True, output=f"Edited {path}")
                return ToolResult(success=False, error=f"old_string not found in {path}")

            elif action == "delete":
                if target.exists():
                    target.unlink()
                    return ToolResult(success=True, output=f"Deleted {path}")
                return ToolResult(success=False, error=f"File not found: {path}")

            elif action == "list":
                if not target.exists():
                    return ToolResult(success=False, error=f"Path not found: {path}")
                items = [str(p.relative_to(root)) if p.is_relative_to(root) else str(p) for p in target.iterdir()]
                return ToolResult(success=True, output="\n".join(items))

            elif action == "mkdir":
                target.mkdir(parents=True, exist_ok=True)
                return ToolResult(success=True, output=f"Created directory {path}")

            return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
