"""
NEXUS TODO TOOL — Claude Code TodoWriteTool adapted for Python.
Task list management for agent workflows.
"""

import json
import os
import time
from typing import List, Dict, Any
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class TodoTool(BaseTool):
    name = "todo"
    description = "Create and manage task lists for complex workflows."
    aliases = ["tasks", "todo_write"]

    def __init__(self, workspace: str = "./workspace"):
        self.workspace = os.path.abspath(workspace)
        self.todo_path = os.path.join(self.workspace, "todos.json")
        os.makedirs(self.workspace, exist_ok=True)
        self.todos: List[Dict[str, Any]] = self._load()

    def _load(self) -> list:
        if os.path.exists(self.todo_path):
            try:
                with open(self.todo_path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, ValueError, OSError, IOError):
                pass
        return []

    def _save(self):
        with open(self.todo_path, "w") as f:
            json.dump(self.todos, f, indent=2)

    def call(
        self,
        action: str = "list",
        content: str = "",
        todo_id: int = None,
        status: str = "pending",
        **kwargs,
    ) -> ToolResult:
        if action == "add":
            todo = {
                "id": len(self.todos) + 1,
                "content": content,
                "status": status,
                "created": time.time(),
            }
            self.todos.append(todo)
            self._save()
            return ToolResult(data=f"Todo #{todo['id']}: {content} [{status}]")

        elif action == "update" and todo_id:
            for t in self.todos:
                if t["id"] == todo_id:
                    t["status"] = status
                    if content:
                        t["content"] = content
                    self._save()
                    return ToolResult(data=f"Todo #{todo_id} updated to [{status}]")
            return ToolResult(error=f"Todo #{todo_id} not found")

        elif action == "list":
            if not self.todos:
                return ToolResult(data="No todos.")
            lines = [f"  #{t['id']} [{t['status']}] {t['content']}" for t in self.todos]
            return ToolResult(data="Todos:\n" + "\n".join(lines))

        return ToolResult(error=f"Unknown action: {action}")
