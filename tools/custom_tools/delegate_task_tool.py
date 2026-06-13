"""Compatibility wrapper for delegating work through NEXUS Hive."""

from typing import Any, Dict

from kernel import get_nexus_kernel
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class DelegateTaskTool(BaseTool):
    """Queue a Hive worker task and return the Hive mission pointer."""

    name = "delegate_task"
    description = (
        "Delegate a task through NEXUS Hive. This is a compatibility alias for "
        "hive_spawn, not a separate worker system."
    )
    aliases = ["hive_delegate", "spawn_worker", "fork_task"]

    def __init__(self, root_dir: str = "."):
        self.root = root_dir

    def call(self, goal: str = "", context: str = "", timeout: int = 120) -> ToolResult:
        if not goal:
            return ToolResult(error="goal is required. What should the Hive worker accomplish?")

        objective = goal
        if context:
            objective = f"{goal}\n\nContext:\n{context}"

        kernel = get_nexus_kernel(self.root)
        result = kernel.hive.spawn_agent(
            objective,
            persona="WORKER",
            persona_description="Compatibility Hive worker for delegated tasks.",
        )
        return ToolResult(data=result)

    def is_read_only(self, input_data=None):
        return False

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "What the Hive worker should accomplish. Be specific."},
                    "context": {"type": "string", "description": "Background info: file paths, error messages, project structure."},
                    "timeout": {"type": "integer", "description": "Compatibility field; Hive runs asynchronously."},
                },
                "required": ["goal"],
            },
        }
