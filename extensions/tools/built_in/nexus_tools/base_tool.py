"""Base classes for NEXUS tools."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    success: bool = True
    output: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTool:
    """Base class for all NEXUS tools."""

    name: str = ""
    description: str = ""

    def __init__(self, root_dir: Optional[str] = None):
        self.root_dir = root_dir
        self._runtime_context: Dict[str, Any] = {}

    def set_runtime_context(self, context: Dict[str, Any]) -> None:
        """Bind per-run ownership and idempotency context for every tool.

        Side-effecting adapters can forward ``idempotency_key`` to external
        systems and inspect ``run_control`` before their commit boundary.
        """
        self._runtime_context = dict(context or {})

    @property
    def idempotency_key(self) -> str:
        return str(self._runtime_context.get("idempotency_key") or "")

    def assert_execution_active(self) -> None:
        control = self._runtime_context.get("run_control")
        fence = getattr(control, "execution_fence", None)
        if callable(fence) and not bool(fence()):
            raise RuntimeError("tool execution fenced because queue lease ownership was lost")
        if control is not None and bool(getattr(control, "cancelled", False)):
            raise RuntimeError("tool execution fenced because run ownership was cancelled")
        cancel_event = getattr(control, "cancel_event", None)
        if cancel_event is not None and callable(getattr(cancel_event, "is_set", None)):
            if cancel_event.is_set():
                raise RuntimeError("tool execution fenced because run ownership was cancelled")

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool. Override in subclasses with real logic."""
        return ToolResult(success=False, error=f"Tool '{self.name}' has no execute() implementation")
