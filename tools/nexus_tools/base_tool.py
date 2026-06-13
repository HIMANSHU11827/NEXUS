"""
NEXUS CLAUDE-CODE TOOL BASE — buildTool pattern adapted for Python.
Each tool has: name, description, input_schema, call(), check_permissions(),
is_concurrency_safe(), is_read_only()
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple
import time


class ToolResult:
    """Standard tool result container."""

    def __init__(
        self,
        data: Any = None,
        error: Optional[str] = None,
        new_messages: Optional[list] = None,
    ):
        self.data = data
        self.error = error
        self.new_messages = new_messages or []
        self.timestamp = time.time()

    @property
    def success(self) -> bool:
        return self.error is None

    def __str__(self) -> str:
        if self.error:
            return f"[TOOL_ERROR]: {self.error}"
        return str(self.data) if self.data else "[OK]"

    def compressed(self, tool_name: str = "default") -> str:
        """Return token-optimized compressed output."""
        from tools.nexus_tools.output_optimizer_tool import OutputOptimizer

        if self.error:
            return f"[ERR] {self.error[:200]}"
        text = str(self.data) if self.data else "[OK]"
        return OutputOptimizer.compress(text, tool_name)


class BaseTool(ABC):
    """Base class for all NEXUS Claude-Code tools."""

    name: str = "base"
    description: str = "Base tool"
    aliases: list = []

    @abstractmethod
    def call(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments."""
        pass

    def check_permissions(
        self, input_data: Dict[str, Any], context: Dict[str, Any] = None
    ) -> Tuple[bool, str]:
        """Check if the operation is permitted. Returns (granted, reason)."""
        return True, "OK"

    def is_concurrency_safe(self, input_data: Dict[str, Any] = None) -> bool:
        """Can this tool run in parallel with others?"""
        return True

    def is_read_only(self, input_data: Dict[str, Any] = None) -> bool:
        """Is this tool non-destructive?"""
        return False

    def get_schema(self) -> Dict[str, Any]:
        """Return the tool's input schema."""
        return {
            "name": self.name,
            "description": self.description,
            "aliases": self.aliases,
        }
