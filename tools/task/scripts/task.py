from __future__ import annotations
__version__ = "1.0.0"
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class TaskTool(BaseTool):
    name = "task"
    description = "Create and manage tasks"

    def _get_store(self) -> Path:
        d = Path(self.root_dir or ".") / ".nexus" / "tasks"
        d.mkdir(parents=True, exist_ok=True)
        return d / "tasks.json"

    def _load(self) -> List[Dict[str, Any]]:
        p = self._get_store()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return []

    def _save(self, tasks: List[Dict[str, Any]]):
        self._get_store().write_text(json.dumps(tasks, indent=2), encoding="utf-8")

    async def execute(self, action: str, id: Optional[str] = None, title: Optional[str] = None, description: Optional[str] = None, status: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            tasks = self._load()
            if action == "create":
                task = {
                    "id": id or f"task-{len(tasks) + 1}",
                    "title": title or "Untitled",
                    "description": description or "",
                    "status": "pending",
                    "created": datetime.now().isoformat()
                }
                tasks.append(task)
                self._save(tasks)
                return ToolResult(success=True, output=f"Created task: {task['id']}")

            elif action == "list":
                if not tasks:
                    return ToolResult(success=True, output="No tasks")
                lines = [f"{t['id']}: [{t['status']}] {t['title']}" for t in tasks]
                return ToolResult(success=True, output="\n".join(lines))

            elif action == "update":
                for t in tasks:
                    if t["id"] == id:
                        if title: t["title"] = title
                        if description: t["description"] = description
                        if status: t["status"] = status
                        self._save(tasks)
                        return ToolResult(success=True, output=f"Updated task {id}")
                return ToolResult(success=False, error=f"Task {id} not found")

            elif action == "delete":
                tasks = [t for t in tasks if t["id"] != id]
                self._save(tasks)
                return ToolResult(success=True, output=f"Deleted task {id}")

            return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
